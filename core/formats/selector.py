"""Format selection, pairing, and filtering logic for Digital Downloader Core."""

from __future__ import annotations

import re
from typing import Sequence

from ..models.media import MediaFormat

_RESOLUTION = re.compile(r"^(\d+)p(\d+)?$")


def sort_formats(formats: Sequence[MediaFormat]) -> list[MediaFormat]:
    """Sort formats: Video first (higher resolution, higher FPS, with audio), then Audio."""
    def sort_key(f: MediaFormat) -> tuple[bool, int, int, bool, str]:
        match = _RESOLUTION.match(f.resolution or "")
        height = int(match.group(1)) if match else 0
        fps = int(match.group(2) or 0) if match else 0
        return (f.type != "video", -height, -fps, not f.has_audio, f.container)

    return sorted(formats, key=sort_key)


def find_format(formats: Sequence[MediaFormat], format_id: str) -> MediaFormat | None:
    """Find a format by its format_id."""
    for f in formats:
        if f.id == format_id:
            return f
    return None


def find_compatible_audio(formats: Sequence[MediaFormat], container: str) -> MediaFormat | None:
    """Find container-compatible audio stream for merging."""
    audio_formats = [f for f in formats if f.type == "audio"]
    if not audio_formats:
        return None
    # Prioritize matching container, then m4a/mp3
    matching = [f for f in audio_formats if f.container == container]
    if matching:
        return matching[0]
    m4a = [f for f in audio_formats if f.container == "m4a"]
    if m4a:
        return m4a[0]
    return audio_formats[0]
