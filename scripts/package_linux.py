"""Digital Downloader: Linux Standalone Packaging Script.

Packages Digital Downloader into a standalone Linux executable / AppImage distribution.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
FRONTEND = ROOT / "frontend"


def build_pyinstaller() -> Path:
    print(">> Running PyInstaller build for Linux...")
    DIST.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "DigitalDownloader-linux-x64",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--add-data",
        f"{FRONTEND}:frontend",
        "--collect-all",
        "yt_dlp",
        "--collect-all",
        "core",
        "--hidden-import",
        "core",
        "--hidden-import",
        "uvicorn",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols",
        "--hidden-import",
        "uvicorn.protocols.http",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.lifespan",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(ROOT / "scripts" / "run_app.py"),
    ]

    subprocess.run(cmd, check=True)
    bin_path = DIST / "DigitalDownloader-linux-x64"
    if not bin_path.is_file():
        raise RuntimeError(f"Build failed: {bin_path} not found.")
    os.chmod(bin_path, 0o755)
    print(f">> Linux standalone executable successfully created at: {bin_path}")
    return bin_path


def main():
    build_pyinstaller()


if __name__ == "__main__":
    main()
