"""Job registry, queue and worker threads."""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..models.job import TERMINAL, Job, JobStatus
from ..models.media import MediaInfo
from ..utils.filenames import ALLOWED_OUTPUT_EXTENSIONS
from ..utils.urls import ValidatedURL, validate_url
from .download_service import DownloadService
from .ffmpeg_service import INSTALL_HINT, find_ffmpeg
from .file_service import is_within, validate_output_directory
from .processing_service import ProcessingPlan, plan_job
from .source_service import SourceService
from .sources.base import MediaSource

logger = logging.getLogger("app.jobs")

MAX_ACTIVE_JOBS = 20  # queued + running
MAX_REMEMBERED_JOBS = 50  # finished jobs kept in memory (history persistence comes later)


class AnalysisCache:
    """Remembers recent analyses so a job can only use format ids that analysis really returned."""

    def __init__(self, ttl: float = 1800.0, max_entries: int = 32) -> None:
        self._ttl, self._max = ttl, max_entries
        self._items: OrderedDict[str, tuple[float, MediaInfo]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, info: MediaInfo) -> None:
        with self._lock:
            self._items[info.url] = (time.monotonic(), info)
            self._items.move_to_end(info.url)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def get(self, url: str) -> MediaInfo | None:
        with self._lock:
            entry = self._items.get(url)
            if entry is None or time.monotonic() - entry[0] > self._ttl:
                self._items.pop(url, None)
                return None
            return entry[1]


@dataclass
class JobRecord:
    job: Job
    source: MediaSource
    url: ValidatedURL
    info: MediaInfo
    plan: ProcessingPlan


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "That download was not found.", status_code=404, reason="unknown_job")


class JobService:
    def __init__(
        self,
        settings: Settings,
        sources: SourceService,
        downloader: DownloadService,
        cache: AnalysisCache,
        history=None,
        store=None,
    ) -> None:
        self._settings = settings
        self._sources = sources
        self._downloader = downloader
        self._cache = cache
        self._history = history
        self._store = store  # optional QueueStore: makes the queue survive restarts
        self._shutting_down = False
        self._records: dict[str, JobRecord] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._workers:
            return
        self._shutting_down = False
        for n in range(self._settings.max_parallel_jobs):
            worker = threading.Thread(target=self._work, name=f"job-worker-{n}", daemon=True)
            worker.start()
            self._workers.append(worker)
        if self._store is not None:
            # Re-analysis needs the network, so restore in the background instead of delaying startup.
            threading.Thread(target=self.restore, name="queue-restore", daemon=True).start()

    def _persist_finished(self, job: Job) -> None:
        """Save a terminal status. Jobs cancelled only because the app is closing stay restorable."""
        if self._store is None:
            return
        if self._shutting_down and job.status is JobStatus.CANCELLED:
            return
        try:
            self._store.finish(job)
        except Exception as exc:  # persistence must never break a download
            logger.error("failed to persist job state: %s", exc)

    def restore(self) -> int:
        """Re-queue downloads that were waiting or running when the app last stopped. Returns how many."""
        if self._store is None:
            return 0
        restored = 0
        for stored in self._store.pending()[:MAX_ACTIVE_JOBS]:
            self._store.delete(stored.id)  # the re-created job gets a fresh id and row
            try:
                self.create(stored.url, stored.format_id, stored.output_format)
                restored += 1
            except AppError as exc:
                logger.warning("could not restore job: %s", exc.message, extra={"job_id": stored.id})
                self._store_failed(stored, exc.message)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("could not restore job: %s", exc, extra={"job_id": stored.id})
        if restored:
            logger.info("restored queued downloads", extra={"operation": "restore", "status": f"{restored} restored"})
        return restored

    def _store_failed(self, stored, message: str) -> None:
        job = Job(url=stored.url, title=stored.title, format_id=stored.format_id, output_format=stored.output_format)
        job.fail("RESTORE_FAILED", message)
        self._persist_finished(job)

    def shutdown(self, timeout: float = 15.0) -> None:
        """Cancel everything and wait for workers, so no download or FFmpeg process outlives the server."""
        self._shutting_down = True
        with self._lock:
            records = list(self._records.values())
        for record in records:
            if record.job.status not in TERMINAL:
                record.job.cancel_if_queued()
                record.job.cancel_event.set()
        for _ in self._workers:
            self._queue.put(None)
        deadline = time.monotonic() + timeout
        for worker in self._workers:
            worker.join(max(0.0, deadline - time.monotonic()))
        self._workers.clear()

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            with self._lock:
                record = self._records.get(job_id)
            if record is None or record.job.status is not JobStatus.QUEUED:
                continue  # cancelled while waiting
            self._downloader.run(record.job, record.source, record.url, record.info, record.plan)
            self._persist_finished(record.job)
            if record.job.status is JobStatus.COMPLETED and self._history is not None:
                try:
                    format_label = getattr(record.plan, "output_ext", "").upper()
                    self._history.record(record.job, source=getattr(record.source, "name", ""), format_label=format_label)
                except Exception as exc:
                    logger.error("failed to record job history: %s", exc)
            self._prune()

    def _prune(self) -> None:
        with self._lock:
            finished = [r for r in self._records.values() if r.job.status in TERMINAL]
            finished.sort(key=lambda r: r.job.created_at)
            for record in finished[: max(0, len(finished) - MAX_REMEMBERED_JOBS)]:
                self._records.pop(record.job.id, None)

    # ---------------------------------------------------------------- operations

    def create(self, url: str, format_id: str, output_format: str | None) -> Job:
        validated = validate_url(url, allowed_ports=self._settings.allowed_ports)
        source = self._sources.detect(validated)
        if source is None:
            raise AppError(ErrorCode.UNSUPPORTED_SOURCE, "This website isn't supported yet.", reason="no_adapter")
        info = self._cache.get(validated.url) or self._sources.analyze(validated)
        # Only ids that analysis returned can ever reach a downloader.
        fmt = next((f for f in info.formats if f.id == format_id), None)
        if fmt is None:
            raise AppError(ErrorCode.FORMAT_NOT_AVAILABLE, "The selected format is no longer available. Analyze the link again.", reason="unknown_format")
        plan = plan_job(info, fmt, output_format)
        if plan.needs_processing and not find_ffmpeg():
            raise AppError(ErrorCode.FFMPEG_NOT_FOUND, INSTALL_HINT, reason="ffmpeg_missing")

        job = Job(url=validated.url, title=info.title, format_id=fmt.id, output_format=output_format)
        with self._lock:
            active = sum(1 for r in self._records.values() if r.job.status not in TERMINAL)
            if active >= MAX_ACTIVE_JOBS:
                raise AppError(ErrorCode.INVALID_REQUEST, "Too many downloads are waiting. Let some finish first.", status_code=429, reason="queue_full")
            self._records[job.id] = JobRecord(job, source, validated, info, plan)
        if self._store is not None:
            try:
                self._store.add(job)
            except Exception as exc:
                logger.error("failed to persist new job: %s", exc)
        self._queue.put(job.id)
        logger.info("job queued", extra={"job_id": job.id, "operation": "create", "status": "queued"})
        return job

    def _record(self, job_id: str) -> JobRecord:
        try:
            canonical = str(uuid.UUID(str(job_id)))
        except ValueError:
            raise _not_found() from None
        with self._lock:
            record = self._records.get(canonical)
        if record is None or canonical != str(job_id):
            raise _not_found()
        return record

    def get(self, job_id: str) -> Job:
        return self._record(job_id).job

    def active_count(self) -> int:
        """Downloads that are queued or running."""
        with self._lock:
            return sum(1 for r in self._records.values() if r.job.status not in TERMINAL)

    def list(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = [r.job for r in self._records.values()]
        return sorted(jobs, key=lambda j: (j.created_at, getattr(j, "sequence_num", 0)), reverse=True)[:limit]

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status in TERMINAL:
            raise AppError(ErrorCode.INVALID_REQUEST, "That download has already finished.", status_code=409, reason="already_terminal")
        if job.cancel_if_queued():
            self._persist_finished(job)
        else:
            job.cancel_event.set()  # running: the runner stops its process/transfer and cleans up
        return job

    def retry(self, job_id: str) -> Job:
        """Start a fresh download for a failed or cancelled one (works after a restart too)."""
        try:
            canonical = str(uuid.UUID(str(job_id)))
        except ValueError:
            raise _not_found() from None
        with self._lock:
            record = self._records.get(canonical)
        if record is not None:
            old = record.job
            if old.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
                raise AppError(ErrorCode.INVALID_REQUEST, "Only failed or cancelled downloads can be retried.", status_code=409, reason="not_retryable")
            url, format_id, output_format = old.url, old.format_id, old.output_format
        else:
            stored = self._store.get(canonical) if self._store is not None else None
            if stored is None:
                raise _not_found()
            if stored.status not in (JobStatus.FAILED.value, JobStatus.CANCELLED.value):
                raise AppError(ErrorCode.INVALID_REQUEST, "Only failed or cancelled downloads can be retried.", status_code=409, reason="not_retryable")
            url, format_id, output_format = stored.url, stored.format_id, stored.output_format
        new_job = self.create(url, format_id, output_format)
        if self._store is not None:
            self._store.delete(canonical)  # the failed row is replaced by the new attempt
        with self._lock:
            self._records.pop(canonical, None)
        return new_job

    def create_batch(self, urls: list[str], mode: str = "best") -> list[dict]:
        """Queue several links at once, picking a format automatically. One bad link never blocks the rest."""
        from concurrent.futures import ThreadPoolExecutor

        from core.formats.selector import pick_best

        unique: list[str] = []
        for raw in urls:
            url = raw.strip()
            if url and url not in unique:
                unique.append(url)

        def one(url: str) -> dict:
            try:
                validated = validate_url(url, allowed_ports=self._settings.allowed_ports)
                info = self._cache.get(validated.url) or self._sources.analyze(validated)
                self._cache.put(info)
                fmt = pick_best(info.formats, mode)
                if fmt is None:
                    raise AppError(ErrorCode.FORMAT_NOT_AVAILABLE, "No downloadable format was found.", reason="no_format")
                job = self.create(validated.url, fmt.id, None)
                return {"url": url, "ok": True, "job_id": job.id, "title": job.title, "error": None}
            except AppError as exc:
                return {"url": url, "ok": False, "job_id": None, "title": None, "error": exc.message}
            except Exception as exc:  # never let one link break the whole batch
                logger.error("batch item failed: %s", exc)
                return {"url": url, "ok": False, "job_id": None, "title": None, "error": "Could not process this link."}

        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(one, unique))

    def completed_file(self, job_id: str) -> Path:
        """Path of a completed job's output, verified to be a media file inside the output directory."""
        job = self.get(job_id)
        path = job.output_path
        output = validate_output_directory(self._settings.output_directory)
        if (
            job.status is not JobStatus.COMPLETED
            or path is None
            or not path.is_file()
            or not is_within(output, path)
            or path.suffix.lstrip(".").lower() not in ALLOWED_OUTPUT_EXTENSIONS
        ):
            raise AppError(ErrorCode.NOT_FOUND, "The downloaded file could not be found.", status_code=404, reason="file_missing")
        return path
