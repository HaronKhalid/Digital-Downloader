"""DownloaderEngine: Unified high-level application boundary for Digital Downloader Core.

Decouples core business logic (analysis, queue, downloads, history) from
FastAPI, desktop shells, or any specific presentation layer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .errors.exceptions import AppError, ErrorCode
from .models.history import HistoryItem
from .models.job import Job, JobStatus
from .models.media import MediaFormat, MediaInfo

logger = logging.getLogger("core.engine")


class DownloaderEngine:
    """Core domain facade for Digital Downloader."""

    def __init__(
        self,
        *,
        source_service: Any = None,
        job_service: Any = None,
        history_service: Any = None,
        settings_service: Any = None,
    ) -> None:
        self._source_service = source_service
        self._job_service = job_service
        self._history_service = history_service
        self._settings_service = settings_service

    def analyze(self, url: str) -> MediaInfo:
        """Analyze URL and return normalized MediaInfo."""
        if not self._source_service:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "Media analysis service is unavailable.")
        return self._source_service.analyze(url)

    def create_download(
        self,
        *,
        url: str,
        format_id: str,
        title: str,
        output_format: str | None = None,
    ) -> Job:
        """Create and queue a new download job."""
        if not self._job_service:
            raise AppError(ErrorCode.DOWNLOAD_FAILED, "Job management service is unavailable.")
        return self._job_service.create(
            url=url,
            title=title,
            format_id=format_id,
            output_format=output_format,
        )

    def get_job(self, job_id: str) -> Job | None:
        """Retrieve a job by its ID."""
        if not self._job_service:
            return None
        return self._job_service.get(job_id)

    def list_jobs(self) -> list[Job]:
        """List active and recent jobs."""
        if not self._job_service:
            return []
        return self._job_service.list_recent()

    def cancel_download(self, job_id: str) -> bool:
        """Cancel an in-progress or queued download."""
        if not self._job_service:
            return False
        return self._job_service.cancel(job_id)

    def get_history(self, limit: int = 50) -> list[HistoryItem]:
        """Retrieve download history."""
        if not self._history_service:
            return []
        return self._history_service.list_recent(limit=limit)

    def delete_history(self, item_id: str) -> bool:
        """Delete an entry from download history."""
        if not self._history_service:
            return False
        return self._history_service.delete(item_id)
