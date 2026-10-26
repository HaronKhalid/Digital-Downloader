"""Downloader protocol for core engine."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from ..models.job import Job
from ..models.media import MediaFormat

ProgressCallback = Callable[[float, int, int | None, float | None, float | None, str], None]


class MediaDownloader(Protocol):
    """Protocol for downloading individual media formats to storage."""

    def download(
        self,
        url: str,
        fmt: MediaFormat,
        dest_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Download format to dest_dir and return final file path."""
        ...
