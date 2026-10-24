from __future__ import annotations

from abc import ABC, abstractmethod

from ...models.media import MediaInfo
from ...utils.urls import ValidatedURL


class MediaSource(ABC):
    """A source adapter. Adapters receive only already-validated URLs and return normalized data."""

    id: str
    label: str

    @abstractmethod
    def can_handle(self, url: ValidatedURL) -> bool: ...

    @abstractmethod
    def analyze(self, url: ValidatedURL) -> MediaInfo: ...
