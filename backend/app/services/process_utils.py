"""Controlled subprocess execution.

Every child process the application starts goes through :func:`run_controlled`:
argument list only (never a shell), caller-supplied minimal environment, merged and
size-limited output captured as a tail, an overall timeout, cooperative cancellation,
and termination of the *whole process tree* so no orphaned FFmpeg/yt-dlp is left behind.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ..core.errors import OperationCancelled

MAX_LINE_CHARS = 2000
_POLL_SECONDS = 0.1


class ProcessCancelled(OperationCancelled):
    """The cancel event was set; the process tree has been terminated."""


class ProcessTimeout(Exception):
    """The overall deadline passed; the process tree has been terminated."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    tail: tuple[str, ...]  # last output lines (stdout and stderr merged)


def windows_kill_args(pid: int) -> list[str]:
    """taskkill invocation that terminates a process and all its children."""
    return ["taskkill", "/PID", str(int(pid)), "/T", "/F"]


def terminate_tree(proc: subprocess.Popen, grace: float = 3.0) -> None:
    """Terminate ``proc`` and every process it started. Safe to call repeatedly."""
    if os.name == "nt":
        if proc.poll() is None:
            subprocess.run(
                windows_kill_args(proc.pid),
                capture_output=True,
                check=False,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    else:
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            pgid = None
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + grace
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            try:  # also reaps grandchildren that outlived the parent
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_controlled(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    cancel: threading.Event | None = None,
    timeout: float | None = None,
    on_line: Callable[[str], None] | None = None,
    cwd: str | os.PathLike | None = None,
    tail_lines: int = 30,
) -> ProcessResult:
    """Run ``args`` to completion. Raises ProcessCancelled / ProcessTimeout / OSError (spawn failure)."""
    kwargs: dict = dict(
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=dict(env), cwd=cwd
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True  # own process group, so we can signal the whole tree

    proc = subprocess.Popen(list(args), **kwargs)
    lines: queue.Queue = queue.Queue()

    def reader() -> None:
        try:
            for raw in iter(proc.stdout.readline, b""):
                lines.put(raw.decode("utf-8", "replace").rstrip("\r\n")[:MAX_LINE_CHARS])
        finally:
            lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    tail: deque[str] = deque(maxlen=tail_lines)
    deadline = time.monotonic() + timeout if timeout else None
    finished_reading = False
    try:
        while True:
            if cancel is not None and cancel.is_set():
                terminate_tree(proc)
                raise ProcessCancelled
            if deadline is not None and time.monotonic() > deadline:
                terminate_tree(proc)
                raise ProcessTimeout
            try:
                item = lines.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                item = ...  # nothing yet
            if item is None:
                finished_reading = True
            elif item is not ...:
                tail.append(item)
                if on_line is not None:
                    on_line(item)
            if finished_reading and proc.poll() is not None:
                break
        return ProcessResult(proc.returncode, tuple(tail))
    finally:
        if proc.poll() is None:
            terminate_tree(proc)
        try:
            proc.stdout.close()
        except OSError:
            pass
