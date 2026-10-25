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


def ensure_ffmpeg() -> None:
    """Ensure ffmpeg.exe and ffprobe.exe are in ROOT/bin before packaging."""
    ffmpeg_exe = BIN / "ffmpeg.exe"
    ffprobe_exe = BIN / "ffprobe.exe"
    if not ffmpeg_exe.is_file() or not ffprobe_exe.is_file():
        print(">> FFmpeg binaries missing in bin/. Running install_ffmpeg.py...")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "install_ffmpeg.py")], check=True)
    if not ffmpeg_exe.is_file():
        raise RuntimeError("Failed to obtain ffmpeg.exe for bundling.")
    print(f">> Confirmed FFmpeg binaries at: {BIN}")


def build_pyinstaller() -> Path:
def build_pyinstaller() -> Path:
    """Run PyInstaller to create dist/DigitalDownloader/."""
    print(">> Running PyInstaller build for Digital Downloader...")
    DIST.mkdir(parents=True, exist_ok=True)
    target_dir = DIST / "DigitalDownloader"
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
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
    return target_dir


def post_process_distribution(target_dir: Path) -> None:
    """Add standalone bin folder, documentation, and default .env."""
    print(">> Post-processing distribution package...")
    dist_bin = target_dir / "bin"
    dist_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("ffmpeg.exe", "ffprobe.exe"):
        src = BIN / exe
        if src.is_file():
            shutil.copy2(src, dist_bin / exe)

    # Copy frontend if not already present
    dist_frontend = target_dir / "frontend"
    if not dist_frontend.exists() and FRONTEND.exists():
        shutil.copytree(FRONTEND, dist_frontend)

    # Copy default configuration
    env_example = ROOT / ".env.example"
    if env_example.is_file():
        shutil.copy2(env_example, target_dir / ".env")

    # Write Quickstart guide
    readme = target_dir / "README.txt"
    readme.write_text(
        "Digital Downloader - Standalone Windows Application\n"
        "===================================================\n\n"
        "1. Double-click DigitalDownloader.exe to launch.\n"
        "2. Your web browser will open automatically to:\n"
        "   http://127.0.0.1:8000\n\n"
        "Everything is bundled:\n"
        "- FFmpeg and FFprobe are included in bin/ (no separate installation needed).\n"
        "- Downloads are safely stored in your Downloads/DigitalDownloader folder.\n"
        "- All media is checked, downloaded, and transcoded locally on this machine.\n\n"
        "To stop the application, close the Digital Downloader command window or press Ctrl+C.\n",
        encoding="utf-8",
    )


def create_zip_archive(target_dir: Path) -> Path:
    """Create dist/DigitalDownloader-windows-x64.zip."""
    zip_path = DIST / "DigitalDownloader-windows-x64.zip"
    print(f">> Compressing release archive to {zip_path.name}...")
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root_dir, _, filenames in os.walk(target_dir):
            for filename in filenames:
                full_path = Path(root_dir) / filename
                rel_path = full_path.relative_to(DIST)
                zf.write(full_path, arcname=str(rel_path))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f">> Release archive built successfully: {zip_path.name} ({size_mb:.1f} MB)")
    return zip_path


def main() -> None:
    print("=" * 60)
    print(" Digital Downloader - Windows Package Builder")
    print("=" * 60)
    ensure_ffmpeg()
    target = build_pyinstaller()
    post_process_distribution(target)
    create_zip_archive(target)
    print("=" * 60)
    print(f" Packaging complete! Distribution folder: {target}")
    print("=" * 60)


if __name__ == "__main__":
    main()
