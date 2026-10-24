"""Source-independent media description. The UI only ever sees this shape."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaFormat:
    id: str  # validated, safe to pass to a downloader later
    type: str  # "video" | "audio"
    container: str  # "mp4", "webm", "m4a", ...
    resolution: str | None  # "1080p" for video, None for audio
    has_audio: bool
    filesize: int | None
    filesize_approximate: bool
    label: str  # human-readable summary


@dataclass(frozen=True)
class MediaInfo:
    source_id: str
    source_label: str
    url: str  # normalized URL that was analyzed
    title: str
    duration: int | None  # seconds
    formats: tuple[MediaFormat, ...]
    thumbnail_url: str | None = None  # as reported by the source (never sent to the browser)
    thumbnail: str | None = None  # verified data: URI embedded by SourceService
