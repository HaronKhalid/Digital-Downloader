"""Standalone Personal Media desktop application launcher."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# In windowed mode (no console), stdout/stderr are None on Windows
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Resolve base directories
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parents[1]
    EXE_DIR = APP_DIR

# Prepend bundled bin/ directories (where ffmpeg, ffprobe, and yt-dlp live) to PATH
bin_dirs = [
    EXE_DIR / "bin",
    APP_DIR / "bin",
    EXE_DIR,
    APP_DIR,
]
for bd in bin_dirs:
    if bd.is_dir():
        current_path = os.environ.get("PATH", "")
        if str(bd.resolve()) not in current_path:
            os.environ["PATH"] = str(bd.resolve()) + os.pathsep + current_path

# Configure default environment: Desktop binds strictly to 127.0.0.1 loopback
os.environ["HOST"] = "127.0.0.1"
os.environ.setdefault("PORT", "8000")
if not os.environ.get("FRONTEND_DIRECTORY"):
    frontend_candidate = APP_DIR / "frontend"
    if frontend_candidate.is_dir():
        os.environ["FRONTEND_DIRECTORY"] = str(frontend_candidate.resolve())

# Discover bundled binaries and export explicit environment variables
for bd in bin_dirs:
    if bd.is_dir():
        ff = bd / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if ff.is_file() and not os.environ.get("FFMPEG_PATH"):
            os.environ["FFMPEG_PATH"] = str(ff.resolve())
            os.environ["FFMPEG_LOCATION"] = str(bd.resolve())
        ytdlp = bd / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
        if ytdlp.is_file() and not os.environ.get("YTDLP_PATH"):
            os.environ["YTDLP_PATH"] = str(ytdlp.resolve())

import uvicorn
from backend.app.main import create_app


def open_browser_when_ready(port: int, max_wait: float = 10.0) -> None:
    """Poll health endpoint and open browser once server is listening."""
    import urllib.request

    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1.0) as resp:
                if resp.status == 200:
                    time.sleep(0.3)
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.3)
    # Fallback open if poll timed out
    webbrowser.open(url)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    bind_host = "127.0.0.1"

    try:
        print("=" * 60)
        print(" Digital Downloader - Standalone Desktop App")
        print(f" Access URL: http://127.0.0.1:{port}")
        print(" Binaries (FFmpeg, FFprobe, yt-dlp) bundled and ready.")
        print("=" * 60)
    except Exception:
        pass

    # Launch browser in background
    browser_thread = threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True)
    browser_thread.start()

    app = create_app()
    uvicorn.run(app, host=bind_host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
