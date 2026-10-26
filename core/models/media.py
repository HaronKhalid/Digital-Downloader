"""Source-independent media description models for Digital Downloader Core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaFormat:
    id: str  # validated, safe format identifier
    type: str  # "video" | "audio"
    container: str  # "mp4", "webm", "m4a", ...
    resolution: str | None = None  # "1080p" for video, None for audio
    has_audio: bool = True
    filesize: int | None = None
    filesize_approximate: bool = False
    label: str = ""  # human-readable summary
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    bitrate: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    requires_merge: bool = False
    download_url: str | None = None



@dataclass(frozen=True)
class MediaInfo:
    source_id: str
    source_label: str
    url: str  # normalized URL that was analyzed
    title: str
    duration: int | None  # seconds
    formats: tuple[MediaFormat, ...]
    thumbnail_url: str | None = None  # as reported by source
    thumbnail: str | None = None  # verified data: URI embedded for display
    uploader: str | None = None
    platform: str | None = None
