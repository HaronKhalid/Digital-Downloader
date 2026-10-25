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
    def __init__(self, settings: Settings, sources: SourceService, downloader: DownloadService, cache: AnalysisCache) -> None:
        self._settings = settings
        self._sources = sources
        self._downloader = downloader
        self._cache = cache
        self._records: dict[str, JobRecord] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._workers:
            return
        for n in range(self._settings.max_parallel_jobs):
            worker = threading.Thread(target=self._work, name=f"job-worker-{n}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def shutdown(self, timeout: float = 15.0) -> None:
        """Cancel everything and wait for workers, so no download or FFmpeg process outlives the server."""
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

    def list(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = [r.job for r in self._records.values()]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status in TERMINAL:
            raise AppError(ErrorCode.INVALID_REQUEST, "That download has already finished.", status_code=409, reason="already_terminal")
        if not job.cancel_if_queued():
            job.cancel_event.set()  # running: the runner stops its process/transfer and cleans up
        return job

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
