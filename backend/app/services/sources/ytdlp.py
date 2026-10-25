"""yt-dlp adapter for an allow-list of domains.

yt-dlp runs as a pinned *subprocess* (argument list, no shell, minimal environment,
timeout, ``--ignore-config``, no plugins), which isolates crashes and keeps cancellation simple.
Only domains in ``ALLOWED_SOURCE_DOMAINS`` are handled.

Security note: yt-dlp performs its own network requests, so the initial URL is validated
by us but the extractor's follow-up requests are not pinned by ``SafeHttpClient``. That is
why this adapter is restricted to an allow-list rather than "any site".
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from ...core.errors import AppError, ErrorCode
from ...models.media import MediaFormat, MediaInfo
from ...utils.urls import ValidatedURL, redact_text
from ..ffmpeg_service import controlled_env
from ..http_client import TransferProgress
from ..process_utils import ProcessTimeout, run_controlled
from .base import DownloadContext, MediaSource

logger = logging.getLogger("app.ytdlp")

Runner = Callable[[list[str], float], tuple[int, bytes, bytes]]

MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_FORMATS = 60
MAX_TITLE = 200
ALLOWED_PROTOCOLS = frozenset({"http", "https", "m3u8", "m3u8_native", "http_dash_segments"})
_FORMAT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=\-]{0,99}$")
_EXT = re.compile(r"^[a-z0-9]{1,5}$")
_RESOLUTION = re.compile(r"^(\d+)p(\d+)?$")

INSTALL_HINT = "The media extractor (yt-dlp) isn't installed. Run scripts\\setup.ps1 again to install it."


def detect_ytdlp() -> tuple[bool, str | None, str | None]:
    """(available, version, message)"""
    if importlib.util.find_spec("yt_dlp") is None:
        return False, None, INSTALL_HINT
    try:
        return True, importlib.metadata.version("yt-dlp"), None
    except importlib.metadata.PackageNotFoundError:
        return True, None, None


def default_runner(args: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    env = controlled_env()
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    try:
        done = subprocess.run(
            args, capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, check=False
        )
    except subprocess.TimeoutExpired:
        raise AppError(ErrorCode.TIMEOUT, "The website took too long to respond.", reason="ytdlp_timeout") from None
    except OSError:
        raise AppError(ErrorCode.SOURCE_UNAVAILABLE, INSTALL_HINT, reason="ytdlp_spawn_failed") from None
    return done.returncode, done.stdout, done.stderr


def map_error(stderr: str) -> AppError:
    """Translate extractor output into a categorized, user-readable error (never echoing raw output)."""
    text = stderr.lower()
    if "unsupported url" in text:
        return AppError(ErrorCode.UNSUPPORTED_SOURCE, "That page isn't supported. Try a link to a single media item.", reason="unsupported_url")
    if "drm" in text:
        return AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "This media is protected by DRM and can't be downloaded.", reason="drm")
    if any(k in text for k in ("sign in", "log in", "login", "private", "members", "premium", "subscri", "http error 401", "http error 403", "forbidden")):
        return AppError(
            ErrorCode.MEDIA_NOT_AVAILABLE,
            "This media needs an account or special permission. Personal Media only works with content that is openly available.",
            reason="auth_required",
        )
    if any(k in text for k in ("http error 404", "http error 410", "not found", "does not exist", "unavailable", "removed", "deleted")):
        return AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That media is no longer available at this address.", reason="not_found")
    if "timed out" in text or "timeout" in text:
        return AppError(ErrorCode.TIMEOUT, "The website took too long to respond.", reason="timeout")
    return AppError(
        ErrorCode.SOURCE_UNAVAILABLE,
        "Couldn't read this media from the website. Check the URL and your connection, then try again.",
        reason="extractor_failed",
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def _normalize_format(raw: object) -> MediaFormat | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("has_drm"):  # True or "maybe": never offer protected streams
        return None
    format_id = raw.get("format_id")
    if not isinstance(format_id, str) or not _FORMAT_ID.match(format_id):
        return None
    ext = str(raw.get("ext") or "").lower()
    if not _EXT.match(ext) or ext == "mhtml" or "storyboard" in str(raw.get("format_note") or "").lower():
        return None
    protocol = raw.get("protocol")
    if protocol is not None and protocol not in ALLOWED_PROTOCOLS:
        return None

    vcodec, acodec = raw.get("vcodec"), raw.get("acodec")
    height = _positive_int(raw.get("height"))
    has_video = vcodec != "none" and (vcodec is not None or height is not None)
    has_audio = acodec != "none"
    if not has_video and not has_audio:
        return None

    exact = _positive_int(raw.get("filesize"))
    size = exact or _positive_int(raw.get("filesize_approx"))
    container = ext.upper()

    if has_video:
        fps = _positive_int(raw.get("fps"))
        resolution = f"{height}p{fps}" if height and fps and fps > 30 else (f"{height}p" if height else None)
        label = f"{resolution or 'Video'} · {container}" + ("" if has_audio else " (no audio)")
        kind = "video"
    else:
        resolution = None
        abr = _positive_int(raw.get("abr"))
        label = f"Audio · {container}" + (f" · {abr} kbps" if abr else "")
        kind = "audio"
    return MediaFormat(
        id=format_id,
        type=kind,
        container=ext,
        resolution=resolution,
        has_audio=has_audio,
        filesize=size,
        filesize_approximate=bool(size) and not exact,
        label=label,
    )


def normalize_info(info: object, *, source_id: str, source_label: str, url: str) -> MediaInfo:
    """Convert yt-dlp's JSON into MediaInfo. Raises AppError for anything we won't handle."""
    if not isinstance(info, dict):
        raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website returned data in an unexpected format.", reason="bad_json")

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
        if len(entries) != 1:
            raise AppError(
                ErrorCode.UNSUPPORTED_SOURCE,
                "This link points to a collection of items. Use the link to one specific item instead.",
                reason="playlist",
            )
        info = entries[0]

    if info.get("is_live"):
        raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "Live streams can't be downloaded.", reason="live")

    formats = [f for f in (_normalize_format(r) for r in (info.get("formats") or [])) if f is not None]
    if not formats:
        raise AppError(
            ErrorCode.MEDIA_NOT_AVAILABLE,
            "No downloadable formats were found for this media.",
            reason="no_formats",
        )

    def sort_key(f: MediaFormat):
        match = _RESOLUTION.match(f.resolution or "")
        height = int(match.group(1)) if match else 0
        fps = int(match.group(2) or 0) if match else 0
        # video first; higher resolution, then higher frame rate, then formats that include audio
        return (f.type != "video", -height, -fps, not f.has_audio, f.container)

    formats.sort(key=sort_key)

    title = info.get("title")
    title = title.strip()[:MAX_TITLE] if isinstance(title, str) and title.strip() else "Untitled"
    duration = _positive_int(info.get("duration"))
    thumb = info.get("thumbnail")
    return MediaInfo(
        source_id=source_id,
        source_label=source_label,
        url=url,
        title=title,
        duration=duration,
        formats=tuple(formats[:MAX_FORMATS]),
        thumbnail_url=thumb if isinstance(thumb, str) and thumb.startswith("https://") else None,
    )


class YtDlpSource(MediaSource):
    id = "ytdlp"
    label = "Web media"

    def __init__(
        self,
        domains: frozenset[str],
        *,
        runner: Runner | None = None,
        timeout: float = 60.0,
        base_command: list[str] | None = None,
    ) -> None:
        self._domains = frozenset(d.lower() for d in domains)
        self._runner = runner or default_runner
        self._timeout = timeout
        self._base_command = list(base_command) if base_command else [sys.executable, "-m", "yt_dlp"]

    def can_handle(self, url: ValidatedURL) -> bool:
        host = url.host
        return any(host == d or host.endswith("." + d) for d in self._domains)

    def build_command(self, url: str) -> list[str]:
        # Argument list only. "--" ends option parsing so the URL can never be read as a flag.
        return [
            *self._base_command,
            "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-cookies", "--no-exec",
            "--dump-single-json", "--no-playlist", "--no-warnings", "--no-progress",
            "--socket-timeout", "15", "--retries", "1", "--extractor-retries", "1",
            "--", url,
        ]

    def analyze(self, url: ValidatedURL) -> MediaInfo:
        available, _, message = detect_ytdlp()
        if not available:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, message or INSTALL_HINT, reason="ytdlp_missing")

        code, out, err = self._runner(self.build_command(url.url), self._timeout)
        if code != 0:
            logger.warning(
                "extractor failed",
                extra={"operation": "ytdlp", "status": "failed", "reason": redact_text(err.decode("utf-8", "replace"))[:300]},
            )
            raise map_error(err.decode("utf-8", "replace"))
        if len(out) > MAX_OUTPUT_BYTES:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website returned more data than expected.", reason="output_too_large")
        try:
            info = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website returned data in an unexpected format.", reason="bad_json") from None
        return normalize_info(info, source_id=self.id, source_label=self.label, url=url.url)

    # ------------------------------------------------------------------ download

    def build_download_command(self, url: str, fmt_id: str, dest_dir: Path, part: int, ctx: DownloadContext) -> list[str]:
        if not _FORMAT_ID.match(fmt_id):  # defence in depth: ids are validated at analysis time too
            raise AppError(ErrorCode.FORMAT_NOT_AVAILABLE, "The selected format is no longer available.", reason="bad_format_id")
        # The output path is a yt-dlp *template*, so a literal "%" in our own directory must be escaped.
        template = str(dest_dir / f"part{part}").replace("%", "%%") + ".%(ext)s"
        command = [
            *self._base_command,
            "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-cookies", "--no-exec",
            "--no-playlist", "--no-warnings", "--no-mtime", "--newline",
            "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2",
            "--max-filesize", str(int(ctx.max_bytes)),
            "--progress-template", PROGRESS_TEMPLATE,
            "-f", fmt_id,
            "-o", template,
        ]
        if ctx.ffmpeg_location:
            command += ["--ffmpeg-location", ctx.ffmpeg_location]
        return [*command, "--", url]

    def download(self, url: ValidatedURL, fmt: MediaFormat, dest_dir: Path, part: int, ctx: DownloadContext) -> Path:
        available, _, message = detect_ytdlp()
        if not available:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, message or INSTALL_HINT, reason="ytdlp_missing")

        def on_line(line: str) -> None:
            progress = parse_progress_line(line)
            if progress is not None:
                ctx.on_progress(progress)

        env = controlled_env()
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        try:
            result = run_controlled(
                self.build_download_command(url.url, fmt.id, dest_dir, part, ctx),
                env=env, cancel=ctx.cancel, timeout=ctx.timeout, on_line=on_line,
            )
        except ProcessTimeout:
            raise AppError(ErrorCode.TIMEOUT, "The download took too long and was stopped.", reason="process_timeout") from None
        except OSError:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, INSTALL_HINT, reason="ytdlp_spawn_failed") from None

        text = "\n".join(result.tail)
        if result.returncode != 0:
            logger.warning(
                "download failed",
                extra={"operation": "ytdlp_download", "status": "failed", "reason": redact_text(text)[-300:]},
            )
            mapped = map_error(text)
            if mapped.reason == "extractor_failed":
                mapped = AppError(ErrorCode.DOWNLOAD_FAILED, "The download failed. Check your connection and try again.", reason="download_failed")
            raise mapped

        produced = find_part_file(dest_dir, part)
        if produced is None:
            if "max-filesize" in text.lower() or "larger than" in text.lower():
                raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That file is larger than the maximum size allowed.", reason="too_large")
            raise AppError(ErrorCode.DOWNLOAD_FAILED, "The download finished but no file was produced.", reason="no_output")
        return produced


# Fields are space-separated; yt-dlp prints "NA" for unknown values.
PROGRESS_TEMPLATE = (
    "download:PMPROG %(progress.downloaded_bytes)s %(progress.total_bytes)s "
    "%(progress.total_bytes_estimate)s %(progress.speed)s %(progress.eta)s"
)
_TEMP_EXTENSIONS = frozenset({"part", "ytdl", "temp", "tmp"})
_PART_FILE = re.compile(r"^part(\d+)\.([a-z0-9]{1,5})$")


def _num(token: str) -> float | None:
    try:
        value = float(token)
    except ValueError:
        return None
    return value if value == value and value >= 0 else None  # rejects NaN and negatives


def parse_progress_line(line: str) -> TransferProgress | None:
    """Parse one PMPROG line into TransferProgress; anything else (including junk) returns None."""
    if not line.startswith("PMPROG "):
        return None
    fields = line.split()[1:]
    if len(fields) != 5:
        return None
    downloaded, total, estimate, speed, eta = (_num(f) for f in fields)
    if downloaded is None:
        return None
    size = total or estimate
    return TransferProgress(int(downloaded), int(size) if size else None, speed, eta)


def find_part_file(directory: Path, part: int) -> Path | None:
    """The finished download for ``part``, ignoring partial/temporary files. Names must match our own scheme."""
    candidates = []
    for path in directory.iterdir():
        match = _PART_FILE.match(path.name)
        if (
            match
            and int(match.group(1)) == part
            and match.group(2) not in _TEMP_EXTENSIONS
            and path.is_file()
            and not path.is_symlink()
        ):
            candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None
