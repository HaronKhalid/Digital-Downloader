"""Digital Downloader: Windows Packaging and Bundling Script.

Bundles Digital Downloader into a standalone Windows distribution with FFmpeg
handled for the user, producing:
  - dist/DigitalDownloader/DigitalDownloader.exe (folder build: nothing is unpacked to %TEMP% at start-up)
  - dist/DigitalDownloader/extension/ (browser extension)
  - dist/DigitalDownloader-windows-x64.zip

A folder build is used on purpose: self-extracting single-file executables are the pattern antivirus
engines distrust most. UPX compression is switched off for the same reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

VERSION = "2.1.0"
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
BIN = ROOT / "bin"
FRONTEND = ROOT / "frontend"
EXTENSION = ROOT / "extension"


def ensure_binaries() -> None:
    """Ensure ffmpeg.exe, ffprobe.exe, and yt-dlp.exe are in ROOT/bin before packaging."""
    print(">> Ensuring all multimedia binaries (FFmpeg, FFprobe, yt-dlp) are present in bin/...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "install_ffmpeg.py")], check=True)
    for name in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe"):
        target = BIN / name
        if not target.is_file():
            raise RuntimeError(f"Missing required binary: {target}")
    print(f">> Confirmed all binaries ready at: {BIN}")


def write_version_file() -> Path:
    """Windows version resource (shows under Properties > Details). Anonymous executables look more suspicious."""
    BUILD.mkdir(parents=True, exist_ok=True)
    a, b, c = (int(x) for x in VERSION.split("."))
    path = BUILD / "version_info.txt"
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Digital Takhleeq'),
      StringStruct('FileDescription', 'Digital Downloader'),
      StringStruct('FileVersion', '{VERSION}.0'),
      StringStruct('InternalName', 'DigitalDownloader'),
      StringStruct('LegalCopyright', 'Copyright (C) 2026 Digital Takhleeq'),
      StringStruct('OriginalFilename', 'DigitalDownloader.exe'),
      StringStruct('ProductName', 'Digital Downloader'),
      StringStruct('ProductVersion', '{VERSION}.0')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return path


def build_pyinstaller() -> Path:
    """Run PyInstaller to create the DigitalDownloader folder build."""
    print(">> Running PyInstaller build for Digital Downloader...")
    DIST.mkdir(parents=True, exist_ok=True)

    icon_path = ROOT / "Assets" / "app_icon.ico"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noupx",
        "--version-file",
        str(write_version_file()),
        "--noconsole",
        "--name",
        "DigitalDownloader",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--add-data",
        f"{FRONTEND};frontend",
        "--add-data",
        f"{EXTENSION};extension",
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
        "--collect-all",
        "webview",
        "--collect-all",
        "pythonnet",
        "--collect-all",
        "clr_loader",
    ]
    if icon_path.is_file():
        cmd.extend(["--icon", str(icon_path)])
    cmd.append(str(ROOT / "scripts" / "run_app.py"))

    subprocess.run(cmd, check=True)
    exe_path = DIST / "DigitalDownloader" / "DigitalDownloader.exe"
    if not exe_path.is_file():
        raise RuntimeError(f"PyInstaller build failed: {exe_path} not found.")
    return exe_path


README_TEXT = """Digital Downloader - portable version
=====================================

1. Unzip this whole folder anywhere (for example Documents).
2. Double-click DigitalDownloader.exe.

If Windows shows "Windows protected your PC":
  click "More info", then "Run anyway". This appears for every new program that is not
  commercially code-signed, it does not mean the app is unsafe.

If your antivirus removes a file: open Windows Security > Virus & threat protection >
Protection history > Restore, then add the DigitalDownloader folder under Exclusions.

Browser extension: open Settings > Browser extension inside the app.
Downloads are saved to your Downloads folder unless you choose another one in Settings.
"""


def selftest(exe_path: Path) -> None:
    """Start the packaged app headless and make sure it really serves its page and finds ffmpeg."""
    print(">> Self-test: starting the packaged app without a window...")
    out = BUILD / "selftest.txt"
    out.unlink(missing_ok=True)
    env = dict(os.environ, SELFTEST_OUT=str(out), PORT="8765")
    subprocess.run([str(exe_path), "--selftest"], check=False, timeout=180, env=env)
    result = out.read_text(encoding="utf-8").strip() if out.is_file() else "no result written"
    print(f">> Self-test result: {result}")
    if result != "SELFTEST OK":
        raise RuntimeError(f"Packaged app self-test failed: {result}")


def create_zip_archive(exe_path: Path) -> Path:
    """Create dist/DigitalDownloader-windows-x64.zip containing the whole app folder."""
    zip_path = DIST / "DigitalDownloader-windows-x64.zip"
    print(f">> Creating distribution zip: {zip_path.name}...")
    if zip_path.exists():
        zip_path.unlink()
    app_dir = exe_path.parent
    (app_dir / "README.txt").write_text(README_TEXT, encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                zf.write(f, Path("DigitalDownloader") / f.relative_to(app_dir))
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f">> Release archive created: {zip_path.name} ({size_mb:.1f} MB)")
    return zip_path


def main() -> None:
    print("=" * 60)
    print(" Digital Downloader - Windows Builder")
    print("=" * 60)
    ensure_binaries()
    exe = build_pyinstaller()
    selftest(exe)
    shutil.copytree(EXTENSION, exe.parent / "extension", dirs_exist_ok=True, ignore=shutil.ignore_patterns("test.mjs", "*.md"))
    create_zip_archive(exe)
    print("=" * 60)
    print(f" Packaging complete! Application: {exe}")
    print("=" * 60)


if __name__ == "__main__":
    main()
