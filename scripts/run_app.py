"""Standalone Personal Media desktop application launcher."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Resolve base directories
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parents[1]
    EXE_DIR = APP_DIR

# Prepend bundled bin/ directories (where ffmpeg and ffprobe live) to PATH
bin_dirs = [
    EXE_DIR / "bin",
    APP_DIR / "bin",
]
for bd in bin_dirs:
    if bd.is_dir():
        current_path = os.environ.get("PATH", "")
        if str(bd.resolve()) not in current_path:
            os.environ["PATH"] = str(bd.resolve()) + os.pathsep + current_path

# Configure default environment for loopback operation
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "8000")
if not os.environ.get("FRONTEND_DIRECTORY"):
    frontend_candidate = APP_DIR / "frontend"
    if frontend_candidate.is_dir():
        os.environ["FRONTEND_DIRECTORY"] = str(frontend_candidate.resolve())

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
    print("=" * 60)
    print(" Digital Downloader - Standalone Desktop App")
    print(f" Running at http://127.0.0.1:{port}")
    print(" FFmpeg binary is bundled and ready.")
    print(" Press Ctrl+C in this window to stop.")
    print("=" * 60)

    # Launch browser in background
    browser_thread = threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True)
    browser_thread.start()

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
