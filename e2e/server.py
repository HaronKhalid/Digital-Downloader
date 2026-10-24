import socket, struct, zlib, sys, os
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ.update(OUTPUT_DIRECTORY=__import__("tempfile").mkdtemp(prefix="pm-out-"), TEMP_DIRECTORY=__import__("tempfile").mkdtemp(prefix="pm-tmp-"), DATABASE_PATH=__import__("tempfile").mkdtemp(prefix="pm-db-") + "/h.sqlite3")
real = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))] if host.endswith(".example") else real(host, port, *a, **k)

import base64, uvicorn
from backend.app.core.config import Settings
from backend.app.core.errors import AppError, ErrorCode
from backend.app.main import create_app
from backend.app.models.media import MediaFormat, MediaInfo
from backend.app.services.source_service import SourceService
from backend.app.services.sources.base import MediaSource

def png(w=320, h=180):
    rows = b"".join(b"\x00" + b"".join(bytes((int(40 + 150 * x / w), int(70 + 90 * y / h), 160)) for x in range(w)) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")

THUMB = "data:image/png;base64," + base64.b64encode(png()).decode()
F = MediaFormat
class Src(MediaSource):
    id, label = "demo", "Internet Archive"
    def can_handle(self, url): return url.host == "media.example"
    def analyze(self, url):
        if url.url.endswith("/gone"): raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That media is no longer available at this address.")
        if url.url.endswith("/hostile"):
            return MediaInfo("demo", "Internet Archive", url.url, "<img src=x onerror=\"document.title='PWNED'\"><b>bold</b> Test", 125,
                (F("v720", "video", "mp4", "720p", True, 10_000_000, False, "x"),), thumbnail=THUMB)
        return MediaInfo("demo", "Internet Archive", url.url,
            "Prelinger Archives: A Very Long Title For An Industrial Film About Everyday Machines And The People Who Built Them (1954)", 3725,
            (F("a", "video", "mp4", "1080p", True, 412_000_000, False, "x"), F("b", "video", "webm", "1080p", False, 230_000_000, True, "x"),
             F("c", "video", "mp4", "720p60", True, 150_000_000, False, "x"), F("d", "video", "mp4", "480p", True, None, False, "x"),
             F("e", "audio", "m4a", None, True, 25_000_000, False, "x"), F("f", "audio", "mp3", None, True, 22_000_000, True, "x")),
            thumbnail=THUMB)

app = create_app(Settings.load(dict(os.environ)), source_service=SourceService([Src()]))
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
