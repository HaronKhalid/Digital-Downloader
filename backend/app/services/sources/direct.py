"""Direct links to media files (``https://host/path/clip.mp4``)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from ...core.errors import AppError, ErrorCode
from ...models.media import MediaFormat, MediaInfo
from ...utils.filenames import ALLOWED_OUTPUT_EXTENSIONS
from ...utils.urls import ValidatedURL
from ..http_client import SafeHttpClient
from .base import MediaSource

AUDIO_EXTENSIONS = frozenset({"mp3", "m4a", "aac", "opus", "ogg", "flac", "wav"})
_OK_CONTENT_TYPES = ("video/", "audio/")
_OK_EXACT = frozenset(
    {"application/octet-stream", "binary/octet-stream", "application/ogg", "application/mp4", "application/x-matroska"}
)
_CONTENT_RANGE_TOTAL = re.compile(r"/(\d+)$")
MAX_TITLE = 200


def file_extension(url: str) -> str:
    return PurePosixPath(unquote(urlsplit(url).path)).suffix.lstrip(".").lower()


class DirectFileSource(MediaSource):
    id = "direct"
    label = "Direct link"

    def __init__(self, client: SafeHttpClient) -> None:
        self._client = client

    def can_handle(self, url: ValidatedURL) -> bool:
        return file_extension(url.url) in ALLOWED_OUTPUT_EXTENSIONS

    def analyze(self, url: ValidatedURL) -> MediaInfo:
        response = self._client.request("HEAD", url.url)
        if response.status in (400, 403, 405, 501):
            # Some servers refuse HEAD. Ask for one byte instead; the body is never read.
            response = self._client.request("GET", url.url, headers={"Range": "bytes=0-0"})

        if response.status in (401, 403):
            raise AppError(
                ErrorCode.MEDIA_NOT_AVAILABLE,
                "This file needs a sign-in or special permission, so it can't be downloaded here.",
                reason=f"http_{response.status}",
            )
        if response.status in (404, 410):
            raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That file is no longer available at this address.", reason=f"http_{response.status}")
        if response.status not in (200, 206):
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website couldn't provide that file right now.", reason=f"http_{response.status}")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not (content_type.startswith(_OK_CONTENT_TYPES) or content_type in _OK_EXACT):
            raise AppError(
                ErrorCode.MEDIA_NOT_AVAILABLE,
                "That link points to a web page or another kind of file, not to a media file.",
                reason="content_type",
            )

        size = self._size(response.status, response.headers)
        ext = file_extension(url.url)
        kind = "audio" if ext in AUDIO_EXTENSIONS else "video"
        fmt = MediaFormat(
            id="direct",
            type=kind,
            container=ext,
            resolution=None,
            has_audio=True,
            filesize=size,
            filesize_approximate=False,
            label=f"{ext.upper()} (original file)",
        )
        stem = PurePosixPath(unquote(urlsplit(url.url).path)).stem or "media"
        return MediaInfo(
            source_id=self.id,
            source_label=self.label,
            url=url.url,
            title=stem[:MAX_TITLE],
            duration=None,
            formats=(fmt,),
        )

    @staticmethod
    def _size(status: int, headers: dict[str, str]) -> int | None:
        if status == 206:
            match = _CONTENT_RANGE_TOTAL.search(headers.get("content-range", ""))
            return int(match.group(1)) if match else None
        length = headers.get("content-length", "")
        return int(length) if length.isdigit() else None
