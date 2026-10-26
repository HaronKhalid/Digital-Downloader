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
        "--add-binary",
        f"{BIN / 'ffmpeg.exe'};.",
        "--add-binary",
        f"{BIN / 'ffprobe.exe'};.",
        "--add-binary",
        f"{BIN / 'yt-dlp.exe'};.",
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
        "--collect-all",
        "core",
        "--hidden-import",
        "core",
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
    """Create dist/DigitalDownloader-windows-x64.zip containing standalone executable and desktop shortcut tool."""
    zip_path = DIST / "DigitalDownloader-windows-x64.zip"
    print(f">> Creating distribution zip: {zip_path.name}...")
    if zip_path.exists():
        zip_path.unlink()

    readme_content = (
        "Digital Downloader - Standalone Desktop App\n"
        "===========================================\n\n"
        "How to use:\n"
        "1. Double-click DigitalDownloader.exe to start.\n"
        "2. The app will launch smoothly without terminal windows and open your browser automatically.\n"
        "3. (Optional) Run Create-Desktop-Shortcut.bat to add a convenient icon to your Desktop.\n\n"
        "Features:\n"
        "- Standalone & Bundled: No Python or FFmpeg installation required.\n"
        "- All media engines (yt-dlp, FFmpeg, FFprobe) are fully bundled.\n"
        "- Downloads save to your Downloads folder or any folder you choose in Settings.\n"
    )

    shortcut_bat = (
        "@echo off\r\n"
        "set SCRIPT=\"%TEMP%\\dd-shortcut.vbs\"\r\n"
        "echo Set oWS = WScript.CreateObject(\"WScript.Shell\") > %SCRIPT%\r\n"
        "echo sLinkFile = oWS.SpecialFolders(\"Desktop\") ^& \"\\Digital Downloader.lnk\" >> %SCRIPT%\r\n"
        "echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %SCRIPT%\r\n"
        "echo oLink.TargetPath = \"%~dp0DigitalDownloader.exe\" >> %SCRIPT%\r\n"
        "echo oLink.WorkingDirectory = \"%~dp0\" >> %SCRIPT%\r\n"
        "echo oLink.Description = \"Digital Downloader\" >> %SCRIPT%\r\n"
        "echo oLink.Save >> %SCRIPT%\r\n"
        "cscript /nologo %SCRIPT%\r\n"
        "if exist %SCRIPT% del %SCRIPT%\r\n"
        "echo Shortcut created on your Desktop!\r\n"
        "timeout /t 3 >nul\r\n"
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, arcname="DigitalDownloader.exe")
        zf.writestr("README.txt", readme_content)
        zf.writestr("Create-Desktop-Shortcut.bat", shortcut_bat)

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
