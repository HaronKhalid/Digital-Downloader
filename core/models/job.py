"""Download job model and state machine for Digital Downloader Core.

State flow:
    QUEUED -> DOWNLOADING -> PROCESSING -> COMPLETED
    any non-terminal state -> FAILED | CANCELLED
"""

from __future__ import annotations

import itertools
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

_seq_counter = itertools.count()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})

_ALLOWED = {
    JobStatus.QUEUED: {JobStatus.DOWNLOADING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.DOWNLOADING: {JobStatus.PROCESSING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class InvalidTransition(Exception):
    pass


class Job:
    def __init__(self, *, url: str, title: str, format_id: str, output_format: str | None = None) -> None:
        self.sequence_num: int = next(_seq_counter)
        self.id = str(uuid.uuid4())
        self.url = url
        self.title = title
        self.format_id = format_id
        self.output_format = output_format
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._status = JobStatus.QUEUED
        self.progress = 0.0
        self.stage = "Waiting to start"
        self.downloaded_bytes = 0
        self.total_bytes: int | None = None
        self.speed_bps: float | None = None
        self.eta_seconds: float | None = None
        self.filename: str | None = None
        self.file_size: int | None = None
        self.output_path: Path | None = None  # internal only; never serialized
        self.error_code: str | None = None
        self.error_message: str | None = None
        self.created_at = _now()
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None

    @property
    def status(self) -> JobStatus:
        with self._lock:
            return self._status

    def transition(self, new: JobStatus) -> None:
        with self._lock:
            if new not in _ALLOWED[self._status]:
                raise InvalidTransition(f"{self._status.value} -> {new.value}")
            self._status = new
            if new is JobStatus.DOWNLOADING and self.started_at is None:
                self.started_at = _now()
            if new in TERMINAL:
                self.completed_at = _now()
                self.speed_bps = None
                self.eta_seconds = None

    def try_start(self) -> bool:
        """Atomically move QUEUED -> DOWNLOADING. False if the job was cancelled in the meantime."""
        with self._lock:
            if self._status is not JobStatus.QUEUED or self.cancel_event.is_set():
                return False
            self.transition(JobStatus.DOWNLOADING)
            return True

    def cancel_if_queued(self) -> bool:
        """Atomically cancel a job that has not started. False if it already started or finished."""
        with self._lock:
            self.cancel_event.set()
            if self._status is not JobStatus.QUEUED:
                return False
            self.stage = "Cancelled"
            self.transition(JobStatus.CANCELLED)
            return True

    def update(
        self,
        *,
        progress: float | None = None,
        stage: str | None = None,
        downloaded: int | None = None,
        total: int | None = None,
        speed: float | None = None,
        eta: float | None = None,
    ) -> None:
        with self._lock:
            if self._status in TERMINAL:
                return
            if progress is not None:
                self.progress = max(self.progress, min(100.0, max(0.0, float(progress))))  # never goes backwards
            if stage is not None:
                self.stage = stage
            if downloaded is not None:
                self.downloaded_bytes = int(downloaded)
            if total is not None:
                self.total_bytes = int(total)
            self.speed_bps = speed
            self.eta_seconds = eta

    def complete(self, path: Path) -> None:
        with self._lock:
            self.output_path = path
            self.filename = path.name
            try:
                self.file_size = path.stat().st_size
            except Exception:
                self.file_size = 0
            self.progress = 100.0
            self.stage = "Completed"
            self.transition(JobStatus.COMPLETED)

    def fail(self, code: str, message: str) -> None:
        with self._lock:
            if self._status in TERMINAL:
                return
            self.error_code, self.error_message, self.stage = code, message, "Failed"
            self.transition(JobStatus.FAILED)

    def mark_cancelled(self) -> None:
        with self._lock:
            if self._status in TERMINAL:
                return
            self.stage = "Cancelled"
            self.transition(JobStatus.CANCELLED)

    def snapshot(self) -> dict:
        """Everything the API exposes. Deliberately contains no filesystem paths."""
        with self._lock:
            iso = lambda d: d.isoformat(timespec="seconds") if d else None
            return {
                "job_id": self.id,
                "status": self._status.value,
                "title": self.title,
                "progress": round(self.progress, 1),
                "stage": self.stage,
                "downloaded_bytes": self.downloaded_bytes,
                "total_bytes": self.total_bytes,
                "speed_bps": self.speed_bps,
                "eta_seconds": self.eta_seconds,
                "filename": self.filename,
                "file_size": self.file_size,
                "error": {"code": self.error_code, "message": self.error_message} if self.error_code else None,
                "created_at": iso(self.created_at),
                "started_at": iso(self.started_at),
                "completed_at": iso(self.completed_at),
            }

    def to_dict(self) -> dict:
        return self.snapshot()
