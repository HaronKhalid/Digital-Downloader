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


def controlled_env() -> dict[str, str]:
    """Environment for child processes: only what FFmpeg needs, nothing sensitive."""
    return {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}


@dataclass(frozen=True)
class FFmpegStatus:
    available: bool
    version: str | None = None
    message: str | None = None


def detect_ffmpeg(timeout: float = 5.0) -> FFmpegStatus:
    executable = shutil.which("ffmpeg")
    if not executable:
        return FFmpegStatus(False, message=INSTALL_HINT)
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=controlled_env(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return FFmpegStatus(False, message="FFmpeg was found but could not be started.")
    match = _VERSION.search(result.stdout or "")
    if result.returncode != 0 or not match:
        return FFmpegStatus(False, message="FFmpeg was found but did not report a valid version.")
    return FFmpegStatus(True, version=match.group(1))
