import os
import socket
import sys
from pathlib import Path

import pytest

_BIN_DIR = Path(__file__).resolve().parents[2] / "bin"
if _BIN_DIR.is_dir() and str(_BIN_DIR) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")


def make_resolver(*ips: str):
    """Fake getaddrinfo returning the given addresses for any host."""

    def resolver(host, port, **kwargs):
        family = lambda ip: socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family(ip), socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return resolver


@pytest.fixture
def public_dns():
    return make_resolver("93.184.216.34")


# ---------------------------------------------------------------- fake source

from backend.app.core.errors import AppError, ErrorCode  # noqa: E402
from backend.app.models.media import MediaFormat, MediaInfo  # noqa: E402
from backend.app.services.sources.base import MediaSource  # noqa: E402


import time as _time  # noqa: E402
from backend.app.services.http_client import TransferProgress  # noqa: E402


class FakeSource(MediaSource):
    """Handles https://media.example/... without touching the network."""

    id = "fake"
    label = "Fake source"

    def can_handle(self, url):
        return url.host == "media.example"

    def analyze(self, url):
        if url.url.endswith("/gone"):
            raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That media is no longer available at this address.")
        return MediaInfo(
            source_id=self.id,
            source_label=self.label,
            url=url.url,
            title="<img src=x onerror=alert(1)> Test clip",
            duration=125,
            formats=(
                MediaFormat("v720", "video", "mp4", "720p", True, 10_000_000, False, "720p · MP4"),
                MediaFormat("a128", "audio", "m4a", None, True, None, False, "Audio · M4A"),
            ),
        )

    def download(self, url, fmt, dest_dir, part, ctx):
        dest = dest_dir / f"part{part}.{fmt.container}"
        total = 100_000
        with open(dest, "xb") as fh:
            for i in range(10):
                if ctx.cancel.is_set():
                    from backend.app.core.errors import OperationCancelled

                    raise OperationCancelled
                fh.write(b"\0" * (total // 10))
                ctx.on_progress(TransferProgress((i + 1) * total // 10, total, 1e6, 0.1))
        return dest
