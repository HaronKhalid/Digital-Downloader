from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...models.media import MediaFormat, MediaInfo
from ...utils.urls import ValidatedURL
from ..http_client import ProgressCallback


@dataclass(frozen=True)
class DownloadContext:
    cancel: threading.Event
    on_progress: ProgressCallback
    max_bytes: int
    ffmpeg_location: str | None = None
    timeout: float = 6 * 3600  # overall limit for one part


class MediaSource(ABC):
    """A source adapter. Adapters receive only already-validated URLs and return normalized data."""

    id: str
    label: str

    @abstractmethod
    def can_handle(self, url: ValidatedURL) -> bool: ...

    @abstractmethod
    def analyze(self, url: ValidatedURL) -> MediaInfo: ...

    @abstractmethod
    def download(self, url: ValidatedURL, fmt: MediaFormat, dest_dir: Path, part: int, ctx: DownloadContext) -> Path:
        """Download one format into ``dest_dir`` as ``part<N>.<ext>`` and return its path."""
