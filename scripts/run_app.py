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


def wait_for_server(port: int, max_wait: float = 10.0) -> bool:
    """Poll health endpoint until the internal loopback server is ready."""
    import urllib.request

    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.8) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def launch_native_desktop_window(port: int) -> None:
    """Open a direct, dedicated native application window without browser chrome or tabs."""
    url = f"http://127.0.0.1:{port}"

    # 1. Primary: Use pywebview (WebView2 / Edge Chromium engine) for native window
    try:
        import webview
        window = webview.create_window(
            title="Digital Downloader",
            url=url,
            width=1120,
            height=760,
            min_size=(800, 560),
            background_color="#0b0f17",
        )
        webview.start(debug=False)
        return
    except Exception:
        pass

    # 2. Secondary fallback: Microsoft Edge in dedicated App Mode (frameless standalone window)
    import subprocess
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidates:
        if os.path.isfile(exe):
            try:
                proc = subprocess.Popen([exe, f"--app={url}", "--new-window"])
                proc.wait()
                return
            except Exception:
                pass

    # 3. Last-resort fallback: open default browser tab
    webbrowser.open(url)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    bind_host = "127.0.0.1"

    try:
        print("=" * 60)
        print(" Digital Downloader - Standalone Desktop App")
        print(f" Internal loopback: http://127.0.0.1:{port}")
        print(" Binaries (FFmpeg, FFprobe, yt-dlp) bundled and ready.")
        print("=" * 60)
    except Exception:
        pass

    app = create_app()

    # Start FastAPI backend in a background daemon thread
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": bind_host, "port": port, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()

    # Wait for server readiness
    wait_for_server(port)

    # Launch native desktop application window (blocks until user closes the window)
    launch_native_desktop_window(port)

    # Clean exit when window is closed
    sys.exit(0)


if __name__ == "__main__":
    main()
