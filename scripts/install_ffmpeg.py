"""Download and configure a standalone FFmpeg binary directly inside the project."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
DOWNLOAD_URL = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip"


def install_ffmpeg() -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_ffmpeg = BIN_DIR / "ffmpeg.exe"
    target_ffprobe = BIN_DIR / "ffprobe.exe"

    if target_ffmpeg.is_file() and target_ffprobe.is_file():
        print(f"FFmpeg is already installed at: {target_ffmpeg}")
        return target_ffmpeg

    print(f"Downloading FFmpeg from {DOWNLOAD_URL}...")
    temp_zip = BIN_DIR / "ffmpeg_temp.zip"

    try:
        def reporthook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                percent = min(100.0, block_num * block_size * 100 / total_size)
                mb_downloaded = (block_num * block_size) / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                sys.stdout.write(f"\rDownloading: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)")
                sys.stdout.flush()

        urllib.request.urlretrieve(DOWNLOAD_URL, temp_zip, reporthook=reporthook)
        print("\nDownload complete. Extracting binaries...")

        with zipfile.ZipFile(temp_zip, "r") as z:
            for item in z.infolist():
                filename = os.path.basename(item.filename)
                if filename in ("ffmpeg.exe", "ffprobe.exe"):
                    print(f"Extracting {filename} -> {BIN_DIR}")
                    with z.open(item) as src, open(BIN_DIR / filename, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    finally:
        if temp_zip.is_file():
            temp_zip.unlink(missing_ok=True)

    # Verify binary
    result = subprocess.run([str(target_ffmpeg), "-version"], capture_output=True, text=True, check=False)
    first_line = (result.stdout or "").splitlines()[0] if result.stdout else "unknown"
    print(f"Verified FFmpeg: {first_line}")

    # Update .env if present
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("FFMPEG_PATH="):
                new_lines.append(f"FFMPEG_PATH={target_ffmpeg}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"FFMPEG_PATH={target_ffmpeg}")
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"Updated .env with FFMPEG_PATH={target_ffmpeg}")

    return target_ffmpeg


YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"


def install_ytdlp() -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_ytdlp = BIN_DIR / "yt-dlp.exe"
    if target_ytdlp.is_file():
        print(f"yt-dlp is already installed at: {target_ytdlp}")
        return target_ytdlp

    print(f"Downloading standalone yt-dlp binary from {YTDLP_URL}...")
    temp_file = BIN_DIR / "yt-dlp_temp.exe"
    try:
        urllib.request.urlretrieve(YTDLP_URL, temp_file)
        if temp_file.is_file() and temp_file.stat().st_size > 5 * 1024 * 1024:
            shutil.move(str(temp_file), str(target_ytdlp))
            print(f"Installed yt-dlp.exe -> {target_ytdlp}")
        else:
            raise RuntimeError("Downloaded yt-dlp binary is invalid or incomplete.")
    finally:
        if temp_file.is_file():
            temp_file.unlink(missing_ok=True)

    result = subprocess.run([str(target_ytdlp), "--version"], capture_output=True, text=True, check=False)
    version = (result.stdout or "").strip()
    print(f"Verified standalone yt-dlp binary version: {version}")
    return target_ytdlp


def install_all() -> None:
    install_ffmpeg()
    install_ytdlp()


if __name__ == "__main__":
    install_all()
