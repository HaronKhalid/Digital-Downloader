"""Digital Downloader: Windows Packaging and Bundling Script.

Bundles Digital Downloader into a standalone Windows distribution with FFmpeg
handled for the user, producing:
  - dist/DigitalDownloader/DigitalDownloader.exe
  - dist/DigitalDownloader/bin/ffmpeg.exe + ffprobe.exe
  - dist/DigitalDownloader/frontend/
  - dist/DigitalDownloader-windows-x64.zip
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
BIN = ROOT / "bin"
FRONTEND = ROOT / "frontend"


def ensure_binaries() -> None:
    """Ensure ffmpeg.exe, ffprobe.exe, and yt-dlp.exe are in ROOT/bin before packaging."""
    print(">> Ensuring all multimedia binaries (FFmpeg, FFprobe, yt-dlp) are present in bin/...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "install_ffmpeg.py")], check=True)
    for name in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe"):
        target = BIN / name
        if not target.is_file():
            raise RuntimeError(f"Missing required binary: {target}")
    print(f">> Confirmed all binaries ready at: {BIN}")


def build_pyinstaller() -> Path:
    """Run PyInstaller to create a single standalone DigitalDownloader.exe."""
    print(">> Running PyInstaller build for Digital Downloader...")
    DIST.mkdir(parents=True, exist_ok=True)

    icon_path = ROOT / "Assets" / "app_icon.ico"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noconsole",
        "--name",
        "DigitalDownloader",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--add-data",
        f"{FRONTEND};frontend",
        "--add-binary",
        f"{BIN / 'ffmpeg.exe'};bin",
        "--add-binary",
        f"{BIN / 'ffprobe.exe'};bin",
        "--add-binary",
        f"{BIN / 'yt-dlp.exe'};bin",
        "--collect-all",
        "yt_dlp",
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
    ]
    if icon_path.is_file():
        cmd.extend(["--icon", str(icon_path)])
    cmd.append(str(ROOT / "scripts" / "run_app.py"))

    subprocess.run(cmd, check=True)
    exe_path = DIST / "DigitalDownloader.exe"
    if not exe_path.is_file():
        raise RuntimeError(f"PyInstaller build failed: {exe_path} not found.")
    return exe_path


def create_zip_archive(exe_path: Path) -> Path:
    """Create dist/DigitalDownloader-windows-x64.zip containing standalone executable and README."""
    zip_path = DIST / "DigitalDownloader-windows-x64.zip"
    print(f">> Creating distribution zip: {zip_path.name}...")
    if zip_path.exists():
        zip_path.unlink()

    readme_content = (
        "Digital Downloader - Standalone Desktop App\n"
        "===========================================\n\n"
        "Double-click DigitalDownloader.exe to start.\n"
        "Your browser will open automatically at http://127.0.0.1:8000\n\n"
        "Features:\n"
        "- Single executable: No Python or FFmpeg installation required.\n"
        "- All extractors and codecs (yt-dlp, FFmpeg, FFprobe) are fully bundled.\n"
        "- Works directly without extracting from zip.\n"
        "- Downloads save to your Downloads/DigitalDownloader folder.\n"
        "- Mobile access: Phones on the same Wi-Fi can connect directly using your PC's IP address.\n"
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, arcname="DigitalDownloader.exe")
        zf.writestr("README.txt", readme_content)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f">> Release archive created: {zip_path.name} ({size_mb:.1f} MB)")
    return zip_path


def main() -> None:
    print("=" * 60)
    print(" Digital Downloader - Standalone Windows Executable Builder")
    print("=" * 60)
    ensure_binaries()
    exe = build_pyinstaller()
    create_zip_archive(exe)
    print("=" * 60)
    print(f" Packaging complete! Standalone executable: {exe}")
    print("=" * 60)


if __name__ == "__main__":
    main()
