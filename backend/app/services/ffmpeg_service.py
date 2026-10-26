"""FFmpeg detection and (later) controlled FFmpeg execution.

Subprocesses are always started from argument lists, never through a shell,
with a minimal environment and a timeout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass

_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE")
_VERSION = re.compile(r"ffmpeg version (\S+)")

INSTALL_HINT = "FFmpeg was not detected. Install FFmpeg, make sure it is on your PATH, and restart the application."


def controlled_env(executable: str | None = None) -> dict[str, str]:
    """Environment for child processes: only what FFmpeg needs, nothing sensitive."""
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    if executable:
        parent = os.path.dirname(executable)
        if parent:
            current = env.get("PATH", "")
            if parent not in current:
                env["PATH"] = f"{parent}{os.pathsep}{current}" if current else parent
    return env


@dataclass(frozen=True)
class FFmpegStatus:
    available: bool
    version: str | None = None
    message: str | None = None


def detect_ffmpeg(timeout: float = 5.0) -> FFmpegStatus:
    executable = find_ffmpeg()
    if not executable:
        return FFmpegStatus(False, message=INSTALL_HINT)
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=controlled_env(executable),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return FFmpegStatus(False, message="FFmpeg was found but could not be started.")
    match = _VERSION.search(result.stdout or "")
    if result.returncode != 0 or not match:
        return FFmpegStatus(False, message="FFmpeg was found but did not report a valid version.")
    return FFmpegStatus(True, version=match.group(1))


import sys
from pathlib import Path


def find_ffmpeg() -> str | None:
    if os.environ.get("FFMPEG_PATH"):
        return os.environ["FFMPEG_PATH"]

    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if getattr(sys, "frozen", False):
        candidates: list[Path] = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "bin" / exe_name)
            candidates.append(Path(sys._MEIPASS) / exe_name)
        exe_parent = Path(sys.executable).parent
        candidates.append(exe_parent / "bin" / exe_name)
        candidates.append(exe_parent / exe_name)
        for c in candidates:
            if c.is_file():
                return str(c)

    return shutil.which("ffmpeg") or (shutil.which("ffmpeg.exe") if sys.platform == "win32" else None)


def find_ffprobe() -> str | None:
    if os.environ.get("FFPROBE_PATH"):
        return os.environ["FFPROBE_PATH"]

    exe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    if getattr(sys, "frozen", False):
        candidates: list[Path] = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "bin" / exe_name)
            candidates.append(Path(sys._MEIPASS) / exe_name)
        exe_parent = Path(sys.executable).parent
        candidates.append(exe_parent / "bin" / exe_name)
        candidates.append(exe_parent / exe_name)
        for c in candidates:
            if c.is_file():
                return str(c)

    return shutil.which("ffprobe") or (shutil.which("ffprobe.exe") if sys.platform == "win32" else None)


