"""Filename sanitization.

Titles and metadata come from remote sources and must never influence a
filesystem path. Everything here produces a *single path component*: no
separators, no traversal, no Windows-reserved names, no hidden/option-like names.
"""

from __future__ import annotations

import re
import unicodedata

DEFAULT_STEM = "media"
MAX_STEM_LENGTH = 120

# Output containers the application is willing to write.
ALLOWED_OUTPUT_EXTENSIONS = frozenset(
    {"mp4", "mkv", "webm", "mov", "mp3", "m4a", "aac", "opus", "ogg", "flac", "wav"}
)

WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*]')
_WHITESPACE = re.compile(r"\s+")
_MULTI_DOT = re.compile(r"\.{2,}")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")
_SAFE_EXT = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def _clean(text: str) -> str:
    # NFKC first so look-alike separators (full-width "／", "＼") become real
    # separators *before* we strip them.
    s = unicodedata.normalize("NFKC", str(text))
    # Drop control, format (incl. bidi overrides such as U+202E), surrogate and unassigned chars.
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("C"))
    s = _FORBIDDEN_CHARS.sub("_", s)
    s = _WHITESPACE.sub(" ", s)
    s = _MULTI_DOT.sub(".", s)
    s = _MULTI_UNDERSCORE.sub("_", s)
    # Windows silently strips trailing dots/spaces; leading dots make hidden files;
    # leading dashes can be mistaken for command-line options.
    return s.strip(" .-_")


def _guard_reserved(stem: str) -> str:
    # Windows treats "CON", "con.txt" and "CON.tar.gz" all as the device CON.
    if stem.split(".", 1)[0].strip().upper() in WINDOWS_RESERVED:
        return f"_{stem}"
    return stem


def sanitize_stem(title: object, *, max_length: int = MAX_STEM_LENGTH) -> str:
    """Turn an arbitrary title into a safe file *stem* (no extension handling)."""
    stem = (_clean(title) if title is not None else "")[:max_length].strip(" .-_")
    return _guard_reserved(stem) if stem else DEFAULT_STEM


def sanitize_filename(name: object, *, max_length: int = MAX_STEM_LENGTH) -> str:
    """Sanitize a full filename, preserving a plausible short extension."""
    cleaned = _clean(name) if name is not None else ""
    stem, ext = cleaned, ""
    dot = cleaned.rfind(".")
    if dot > 0 and _SAFE_EXT.match(cleaned[dot:]):
        stem, ext = cleaned[:dot], cleaned[dot:].lower()
    stem = stem[: max(1, max_length - len(ext))].strip(" .-_") or DEFAULT_STEM
    return _guard_reserved(stem) + ext


def build_output_filename(title: object, extension: str) -> str:
    """``<sanitized title>.<allow-listed extension>`` — the only way output names are made."""
    ext = str(extension).lower().lstrip(".")
    if ext not in ALLOWED_OUTPUT_EXTENSIONS:
        raise ValueError(f"Unsupported output extension: {extension!r}")
    return f"{sanitize_stem(title, max_length=MAX_STEM_LENGTH)}.{ext}"
