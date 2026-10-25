"""Runs one job from start to finish.

    disk check -> download part(s) with bounded retries -> FFmpeg if needed -> safe finalize

Whatever happens (success, failure, cancellation, unexpected crash) the job's temporary
directory is removed, and the job ends in exactly one terminal state.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import time
from pathlib import Path

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode, OperationCancelled
from ..models.job import Job, JobStatus
from ..models.media import MediaInfo
from ..utils.filenames import build_output_filename
from ..utils.formatting import format_bytes
from ..utils.urls import ValidatedURL
from .ffmpeg_service import find_ffmpeg
from .file_service import (
    PathSafetyError,
    job_temp_dir,
    remove_job_dir,
    reserve_destination,
    validate_output_directory,
)
from .http_client import TransferProgress
from .processing_service import ProcessingPlan, run_processing
from .sources.base import DownloadContext, MediaSource

logger = logging.getLogger("app.download")

# Retrying is limited and only for failures that can plausibly succeed on a second attempt.
RETRY_DELAYS = (2.0, 5.0)
TRANSIENT_REASONS = frozenset({"read_timeout", "connection_lost", "connect_failed", "timeout"})
DISK_MARGIN = 256 * 1024**2  # always keep this much free
UNKNOWN_SIZE_MIN_FREE = 1024**3  # when the size is unknown, require at least this much free
DOWNLOAD_SHARE_WITH_PROCESSING = 85.0  # progress % reserved for downloading when FFmpeg follows
DOWNLOAD_SHARE_ALONE = 99.0


class DownloadService:
    def __init__(self, settings: Settings, *, retry_delays: tuple[float, ...] = RETRY_DELAYS) -> None:
        self._settings = settings
        self._retry_delays = retry_delays

    # ------------------------------------------------------------------ entry

    def run(self, job: Job, source: MediaSource, url: ValidatedURL, info: MediaInfo, plan: ProcessingPlan) -> None:
        started = time.monotonic()
        job_dir = job_temp_dir(self._settings.temp_directory, job.id)
        try:
            if not job.try_start():
                job.mark_cancelled()
                return
            self._log(job, "started", started)
            job_dir.mkdir(parents=True, exist_ok=False)
            self._check_limits_and_disk(plan, job_dir)
            parts = self._download_parts(job, source, url, plan, job_dir)
            result, effective = self._process(job, plan, parts, job_dir, info)
            destination = self._finalize(info, effective, result)
            job.complete(destination)
            self._log(job, "completed", started)
        except OperationCancelled:
            job.mark_cancelled()
            self._log(job, "cancelled", started)
        except AppError as exc:
            job.fail(exc.code.value, exc.message)
            logger.warning(
                "job failed",
                extra={"job_id": job.id, "operation": "run", "status": "failed", "error_code": exc.code.value,
                       "reason": exc.reason, "duration_ms": int((time.monotonic() - started) * 1000)},
            )
        except Exception:
            logger.exception("job crashed", extra={"job_id": job.id, "operation": "run", "status": "failed"})
            job.fail(ErrorCode.UNKNOWN_ERROR.value, "Something went wrong. Check the application log for details.")
        finally:
            self._cleanup(job, job_dir)

    # ------------------------------------------------------------------ steps

    def _check_limits_and_disk(self, plan: ProcessingPlan, job_dir: Path) -> None:
        expected = plan.expected_bytes
        if expected > self._settings.max_download_bytes:
            raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That file is larger than the maximum size allowed.", reason="too_large")

        temp_root = job_dir.parent
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            output = validate_output_directory(self._settings.output_directory)
            output.mkdir(parents=True, exist_ok=True)
        except (OSError, PathSafetyError):
            raise AppError(ErrorCode.PERMISSION_DENIED, "Personal Media couldn't use the output folder. Check the folder and its permissions.", reason="output_not_writable") from None

        # Peak temp usage: downloaded parts plus (if FFmpeg runs) the processed copy.
        temp_need = int(expected * 1.1) * (2 if plan.needs_processing else 1) + DISK_MARGIN if expected else UNKNOWN_SIZE_MIN_FREE
        self._require_free(temp_root, temp_need)
        if os.stat(temp_root).st_dev != os.stat(output).st_dev:  # a move across drives is a real copy
            self._require_free(output, int(expected * 1.05) + DISK_MARGIN if expected else UNKNOWN_SIZE_MIN_FREE)

    @staticmethod
    def _require_free(path: Path, needed: int) -> None:
        free = shutil.disk_usage(path).free
        if free < needed:
            raise AppError(
                ErrorCode.DISK_SPACE_LOW,
                f"Not enough disk space. Required: {format_bytes(needed)}, available: {format_bytes(free)}.",
                reason="disk_space_low",
            )

    def _download_parts(self, job: Job, source: MediaSource, url: ValidatedURL, plan: ProcessingPlan, job_dir: Path) -> list[Path]:
        expected = [max(f.filesize or 0, 0) for f in plan.parts]
        known = [e for e in expected if e]
        weights = [e or (sum(known) / len(known) if known else 1) for e in expected]
        total_weight = sum(weights)
        share = DOWNLOAD_SHARE_WITH_PROCESSING if plan.needs_processing else DOWNLOAD_SHARE_ALONE
        ffmpeg = find_ffmpeg()

        paths: list[Path] = []
        done_weight = 0.0
        done_bytes = 0
        for index, fmt in enumerate(plan.parts):
            if len(plan.parts) > 1:
                job.update(stage="Downloading video" if fmt.type == "video" else "Downloading audio")
            else:
                job.update(stage="Downloading")
            sizes = list(expected)

            def on_progress(p: TransferProgress, index=index, done_weight=done_weight, done_bytes=done_bytes, sizes=sizes) -> None:
                if p.total:
                    sizes[index] = p.total
                fraction = (p.downloaded / p.total) if p.total else 0.0
                overall = (done_weight + min(1.0, fraction) * weights[index]) / total_weight * share
                total = sum(sizes) if all(sizes) else None
                downloaded = done_bytes + p.downloaded
                eta = p.eta
                if total and p.speed and p.speed > 0:
                    eta = max(0.0, (total - downloaded) / p.speed)
                job.update(progress=overall, downloaded=downloaded, total=total, speed=p.speed, eta=eta)

            ctx = DownloadContext(
                cancel=job.cancel_event, on_progress=on_progress,
                max_bytes=self._settings.max_download_bytes, ffmpeg_location=ffmpeg,
            )
            path = self._download_with_retry(job, source, url, fmt, job_dir, index, ctx)
            paths.append(path)
            done_weight += weights[index]
            done_bytes += path.stat().st_size
        return paths

    def _download_with_retry(self, job, source, url, fmt, job_dir: Path, index: int, ctx: DownloadContext) -> Path:
        attempt = 0
        while True:
            try:
                return source.download(url, fmt, job_dir, index, ctx)
            except AppError as exc:
                transient = exc.reason in TRANSIENT_REASONS
                if not transient or attempt >= len(self._retry_delays):
                    raise
                delay = self._retry_delays[attempt]
                attempt += 1
                for leftover in job_dir.glob(f"part{index}.*"):  # restart the part from scratch (no resume yet)
                    leftover.unlink(missing_ok=True)
                logger.info("retrying download", extra={"job_id": job.id, "operation": "retry", "status": f"attempt {attempt}", "reason": exc.reason})
                job.update(stage=f"Connection problem. Retrying in {int(delay)} s…")
                if job.cancel_event.wait(delay):
                    raise OperationCancelled from None

    def _process(self, job: Job, plan: ProcessingPlan, parts: list[Path], job_dir: Path, info: MediaInfo):
        effective = plan
        actual_ext = parts[0].suffix.lstrip(".").lower()
        if not plan.needs_processing and actual_ext != plan.output_ext:
            # The source delivered a different container than announced: convert instead of mislabelling it.
            op = "convert_audio" if plan.parts[0].type == "audio" else "remux"
            effective = dataclasses.replace(plan, operation=op)
        if not effective.needs_processing:
            return parts[0], effective

        job.transition(JobStatus.PROCESSING)
        stage = {"merge": "Merging audio and video…", "convert_audio": "Converting audio…"}.get(effective.operation, "Converting video…")
        job.update(stage=stage, progress=DOWNLOAD_SHARE_WITH_PROCESSING)
        out = run_processing(
            effective, parts, job_dir, duration=info.duration, cancel=job.cancel_event,
            on_fraction=lambda f: job.update(progress=DOWNLOAD_SHARE_WITH_PROCESSING + 14.0 * f),
        )
        return out, effective

    def _finalize(self, info: MediaInfo, plan: ProcessingPlan, result: Path) -> Path:
        try:
            output = validate_output_directory(self._settings.output_directory)
            output.mkdir(parents=True, exist_ok=True)
            destination = reserve_destination(output, build_output_filename(info.title, plan.output_ext))
        except (OSError, PathSafetyError):
            raise AppError(ErrorCode.PERMISSION_DENIED, "Personal Media couldn't write to the output folder. Check the folder and its permissions.", reason="output_not_writable") from None
        try:
            shutil.move(str(result), str(destination))  # replaces our empty placeholder
        except OSError as exc:
            destination.unlink(missing_ok=True)
            code = ErrorCode.DISK_SPACE_LOW if getattr(exc, "errno", None) == 28 else ErrorCode.PERMISSION_DENIED
            raise AppError(code, "The finished file couldn't be saved to the output folder.", reason="move_failed") from None
        return destination

    def _cleanup(self, job: Job, job_dir: Path) -> None:
        try:
            remove_job_dir(self._settings.temp_directory, job_dir)
        except (OSError, PathSafetyError):
            logger.warning("temp cleanup failed", extra={"job_id": job.id, "operation": "cleanup", "status": "failed"})
        if job_dir.exists():
            logger.warning("temp directory still present", extra={"job_id": job.id, "operation": "cleanup", "status": "leftover"})

    @staticmethod
    def _log(job: Job, status: str, started: float) -> None:
        logger.info("job " + status, extra={"job_id": job.id, "operation": "run", "status": status,
                                              "duration_ms": int((time.monotonic() - started) * 1000)})
