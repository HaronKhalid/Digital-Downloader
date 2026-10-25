"""Source detection, analysis and thumbnail embedding."""

from __future__ import annotations

import base64
import dataclasses
import logging

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..models.media import MediaInfo
from ..utils.urls import ValidatedURL
from .http_client import SafeHttpClient
from .sources.base import MediaSource
from .sources.direct import DirectFileSource
from .sources.ytdlp import YtDlpSource

logger = logging.getLogger("app.sources")

MAX_THUMBNAIL_BYTES = 1_500_000
UNSUPPORTED_MESSAGE = (
    "This website isn't supported yet. You can use a direct link to a media file "
    "(for example ending in .mp4 or .mp3) or a page on a supported site."
)


def sniff_image_type(data: bytes) -> str | None:
    """Identify raster images by content, never by what the server claims. SVG is excluded on purpose."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


class SourceService:
    def __init__(self, sources: list[MediaSource], http_client: SafeHttpClient | None = None) -> None:
        self._sources = sources
        self._http = http_client

    def detect(self, url: ValidatedURL) -> MediaSource | None:
        return next((s for s in self._sources if s.can_handle(url)), None)

    def analyze(self, url: ValidatedURL) -> MediaInfo:
        source = self.detect(url)
        if source is None:
            raise AppError(ErrorCode.UNSUPPORTED_SOURCE, UNSUPPORTED_MESSAGE, reason="no_adapter")
        info = source.analyze(url)
        if info.thumbnail_url:
            info = dataclasses.replace(info, thumbnail=self._embed_thumbnail(info.thumbnail_url))
        return info

    def _embed_thumbnail(self, thumbnail_url: str) -> str | None:
        """Fetch through the safe client and return a data: URI, or None. Never raises."""
        if self._http is None:
            return None
        try:
            response = self._http.request("GET", thumbnail_url, headers={"Accept": "image/*"}, max_body=MAX_THUMBNAIL_BYTES)
        except AppError as exc:
            logger.info("thumbnail skipped", extra={"operation": "thumbnail", "status": "skipped", "reason": exc.reason})
            return None
        mime = sniff_image_type(response.body) if response.status == 200 else None
        if mime is None:
            return None
        return f"data:{mime};base64,{base64.b64encode(response.body).decode('ascii')}"


def build_source_service(settings: Settings, http_client: SafeHttpClient | None = None) -> SourceService:
    client = http_client or SafeHttpClient(allowed_ports=settings.allowed_ports)
    return SourceService(
        [DirectFileSource(client), YtDlpSource(settings.source_domains, settings=settings)],
        http_client=client,
    )
