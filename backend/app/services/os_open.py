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
    target = str(path)
    if sys.platform == "win32":
        if select:
            subprocess.Popen(["explorer", f"/select,{target}"])  # argument list, no shell
        else:
            os.startfile(target)  # noqa: S606 - path validated by the caller
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", target] if select else ["open", target])
    else:
        subprocess.Popen(
            ["xdg-open", str(path.parent if select else path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
