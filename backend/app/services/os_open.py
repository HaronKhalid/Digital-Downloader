"""Open a finished file or its folder with the operating system.

Only ever called with paths the server itself produced (resolved from a job record, checked to
lie inside the output directory), never with a client-supplied path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_in_os(path: Path, *, select: bool = False) -> None:
    """Open ``path`` with the default application, or reveal it in the file manager when ``select``."""
    target_path = Path(path).resolve()
    if sys.platform == "win32":
        if select:
            folder = target_path if target_path.is_dir() else target_path.parent
            try:
                cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                subprocess.Popen(["explorer.exe", norm_folder], creationflags=cf)
            except Exception:
                os.startfile(norm_folder)
        else:
            os.startfile(os.path.normpath(str(target_path)))  # noqa: S606 - path validated by the caller
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target_path)] if select else ["open", str(target_path)])
    else:
        subprocess.Popen(
            ["xdg-open", str(target_path.parent if select else target_path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
