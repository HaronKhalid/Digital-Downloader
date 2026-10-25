"""Direct links to media files (``https://host/path/clip.mp4``)."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from ...core.errors import AppError, ErrorCode
from ...models.media import MediaFormat, MediaInfo
from ...utils.filenames import ALLOWED_OUTPUT_EXTENSIONS
from ...utils.urls import ValidatedURL
from ..http_client import SafeHttpClient, error_for_status
from .base import DownloadContext, MediaSource

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

        if response.status not in (200, 206):
            raise error_for_status(response.status)

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

    def download(self, url: ValidatedURL, fmt: MediaFormat, dest_dir: Path, part: int, ctx: DownloadContext) -> Path:
        if fmt.id != "direct" or fmt.container not in ALLOWED_OUTPUT_EXTENSIONS:
            raise AppError(ErrorCode.FORMAT_NOT_AVAILABLE, "The selected format is no longer available.", reason="bad_format")
        dest = dest_dir / f"part{part}.{fmt.container}"  # generated name; the URL never influences the path
        self._client.download_file(
            url.url, dest, max_bytes=ctx.max_bytes, cancel=ctx.cancel, on_progress=ctx.on_progress
        )
        return dest
