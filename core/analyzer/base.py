"""Abstract Media Analyzer interface for Digital Downloader Core."""

from __future__ import annotations

from typing import Protocol

from ..models.media import MediaInfo


class MediaAnalyzer(Protocol):
    """Protocol for components that validate URLs and extract media metadata."""

    def can_handle(self, url: str) -> bool:
        """Check if analyzer can handle the given URL."""
        ...

    def analyze(self, url: str) -> MediaInfo:
        """Analyze URL and return normalized MediaInfo."""
        ...
