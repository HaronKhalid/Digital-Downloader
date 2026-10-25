"""App with a stub media source (no network needed) for the browser checks in run.py."""
import base64, os, shutil, socket, struct, sys, tempfile, time, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.gettempdir()) / "pm-e2e"  # shared with run.py
shutil.rmtree(WORK, ignore_errors=True)
(WORK / "out").mkdir(parents=True)
os.environ.update(OUTPUT_DIRECTORY=str(WORK / "out"), TEMP_DIRECTORY=str(WORK / "temp"), DATABASE_PATH=str(WORK / "db" / "h.sqlite3"))

real = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, *a, **k: (
    [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))] if host.endswith(".example") else real(host, port, *a, **k)
)

import uvicorn
from backend.app.core.config import Settings
from backend.app.core.errors import AppError, ErrorCode, OperationCancelled
from backend.app.main import create_app
from backend.app.models.media import MediaFormat as F, MediaInfo
from backend.app.services.http_client import TransferProgress
from backend.app.services.source_service import SourceService
from backend.app.services.sources.base import MediaSource


def png(w=320, h=180):
    rows = b"".join(b"\x00" + b"".join(bytes((int(40 + 150 * x / w), int(70 + 90 * y / h), 160)) for x in range(w)) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


THUMB = "data:image/png;base64," + base64.b64encode(png()).decode()
TITLE = "Prelinger Archives: A Very Long Title For An Industrial Film About Everyday Machines (1954)"


class Src(MediaSource):
    id, label = "demo", "Internet Archive"

    def can_handle(self, url):
        return url.host == "media.example"

    def analyze(self, url):
        if url.url.endswith("/gone"):
            raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That media is no longer available at this address.")
        if url.url.endswith("/hostile"):
            return MediaInfo("demo", "Internet Archive", url.url, "<img src=x onerror=\"document.title='PWNED'\"><b>bold</b> Test", 125,
                             (F("v720", "video", "mp4", "720p", True, 10_000_000, False, "x"),), thumbnail=THUMB)
        return MediaInfo("demo", "Internet Archive", url.url, TITLE, 3725,
            (F("a", "video", "mp4", "1080p", True, 412_000_000, False, "x"), F("b", "video", "webm", "1080p", False, 230_000_000, True, "x"),
             F("c", "video", "mp4", "720p60", True, 150_000_000, False, "x"), F("d", "video", "mp4", "480p", True, None, False, "x"),
             F("e", "audio", "m4a", None, True, 25_000_000, False, "x"), F("f", "audio", "mp3", None, True, 22_000_000, True, "x")),
            thumbnail=THUMB)

    def download(self, url, fmt, dest_dir, part, ctx):
        dest = dest_dir / f"part{part}.{fmt.container}"
        total, chunks = 3_000_000, 24
        with open(dest, "xb") as fh:
            for i in range(1, chunks + 1):
                if ctx.cancel.is_set():
                    raise OperationCancelled
                time.sleep(0.12)
                if url.url.endswith("/fail") and i == 8:
                    raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "This file needs a sign-in or special permission, so it can't be downloaded here.", reason="http_403")
                fh.write(b"\0" * (total // chunks))
                ctx.on_progress(TransferProgress(i * total // chunks, total, 1_048_576.0, (chunks - i) * 0.12))
        return dest


def opener(path, select=False):
    with open(WORK / "open.log", "a") as log:
        log.write(f"{'folder' if select else 'file'}\t{path}\n")


app = create_app(Settings.load(dict(os.environ)), source_service=SourceService([Src()]), opener=opener)
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
