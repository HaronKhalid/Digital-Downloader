"""Filesystem safety helpers.

All paths the application writes to are derived from a known root plus
validated components. Nothing derived from a URL, title or other remote
metadata may choose a location on disk.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

_SEPARATORS = re.compile(r"[\\/]")


class PathSafetyError(ValueError):
    """A path or path component failed validation."""


def is_within(base: Path, candidate: Path) -> bool:
    """True if ``candidate`` is ``base`` or lies beneath it (after resolving symlinks)."""
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _check_component(part: object) -> str:
    if not isinstance(part, str) or not part or "\x00" in part:
        raise PathSafetyError("Invalid path component.")
    # Evaluate against both path flavours so behaviour is identical on every OS.
    if PureWindowsPath(part).is_absolute() or PureWindowsPath(part).drive or PurePosixPath(part).is_absolute():
        raise PathSafetyError("Absolute paths are not allowed.")
    if any(segment == ".." for segment in _SEPARATORS.split(part)):
        raise PathSafetyError("Path traversal is not allowed.")
    return part


def safe_join(base: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``base``, guaranteeing the result is strictly inside ``base``."""
    base_resolved = Path(base).resolve()
    checked = [_check_component(p) for p in parts]
    target = base_resolved.joinpath(*checked).resolve()
    if target == base_resolved or not is_within(base_resolved, target):
        raise PathSafetyError("Path escapes the permitted directory.")
    return target


def job_temp_dir(temp_root: Path, job_id: str) -> Path:
    """Per-job scratch directory. ``job_id`` must be a canonical UUID."""
    try:
        canonical = str(uuid.UUID(str(job_id)))
    except ValueError:
        raise PathSafetyError("Invalid job id.") from None
    if canonical != str(job_id):  # strict: one id string <-> one directory
        raise PathSafetyError("Invalid job id.")
    return safe_join(Path(temp_root), f"job-{canonical}")


def remove_job_dir(temp_root: Path, job_dir: Path) -> None:
    """Delete a job directory, but only if it sits strictly inside ``temp_root``."""
    root = Path(temp_root).resolve()
    target = Path(job_dir).resolve()
    if target == root or not is_within(root, target):
        raise PathSafetyError("Refusing to delete outside the temp directory.")
    shutil.rmtree(target, ignore_errors=True)


def validate_output_directory(path: str | Path) -> Path:
    """Validate a user-chosen output directory and return it resolved."""
    p_str = str(path).strip()
    if "\x00" in p_str:
        raise PathSafetyError("Null bytes are not permitted in paths.")
    if p_str.startswith(("\\\\", "//")):
        raise PathSafetyError("Network shares and device namespaces are not permitted.")
    try:
        raw = Path(path).expanduser()
        if not raw.is_absolute():
            raise PathSafetyError("The output directory must be an absolute path.")
        resolved = raw.resolve()
    except (ValueError, RuntimeError) as exc:
        raise PathSafetyError(f"Invalid path: {exc}") from exc
    if resolved.is_file():
        raise PathSafetyError("The output directory cannot be an existing file.")
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise PathSafetyError("Choose a dedicated folder, not a drive root or your home folder.")
    return resolved


def unique_destination(directory: Path, filename: str) -> Path:
    """A non-existing path inside ``directory``; appends " (n)" rather than overwriting."""
    first = safe_join(directory, filename)
    if not first.exists():
        return first
    stem, suffix = first.stem, first.suffix
    for n in range(1, 1000):
        candidate = safe_join(directory, f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
    raise PathSafetyError("Too many files with the same name.")


def ensure_runtime_directories(output: Path, temp: Path, database_file: Path) -> None:
    for directory in (output, temp, database_file.parent):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except (OSError, NotImplementedError):
            pass
    if database_file.is_file():
        try:
            database_file.chmod(0o600)
        except (OSError, NotImplementedError):
            pass


def reserve_destination(directory: Path, filename: str) -> Path:
    """Atomically claim a non-existing file name in ``directory`` (creates an empty placeholder).

    Using exclusive creation means two jobs finishing at the same moment can never pick the same
    name or overwrite each other's file.
    """
    candidate = safe_join(directory, filename)
    stem, suffix = candidate.stem, candidate.suffix
    for n in range(0, 1000):
        path = candidate if n == 0 else safe_join(directory, f"{stem} ({n}){suffix}")
        try:
            with open(path, "xb"):
                pass
            return path
        except FileExistsError:
            continue
    raise PathSafetyError("Too many files with the same name.")


_JOB_DIR_NAME = re.compile(r"^job-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def cleanup_abandoned_temp(temp_root: Path, older_than_seconds: float = 600.0) -> int:
    """Delete leftover ``job-<uuid>`` directories (e.g. after a crash). Returns how many were removed.

    Only real directories whose names match our own scheme are touched, never symlinks and
    never anything else that happens to live in the temp folder.
    """
    root = Path(temp_root)
    if not root.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - older_than_seconds
    for child in root.iterdir():
        if not _JOB_DIR_NAME.match(child.name) or child.is_symlink() or not child.is_dir():
            continue
        try:
            if child.stat().st_mtime <= cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
