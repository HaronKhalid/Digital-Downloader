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
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
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
ALLOWED_PROTOCOLS = frozenset({
    "http", "https", "m3u8", "m3u8_native", "https+m3u8", "http+m3u8",
    "http_dash_segments", "dash"
})
_FORMAT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=+\-:@]{0,99}$")
_EXT = re.compile(r"^[a-z0-9]{1,5}$")
_RESOLUTION = re.compile(r"^(\d+)p(\d+)?$")

INSTALL_HINT = "The media extractor (yt-dlp) isn't installed. Run scripts\\setup.ps1 again to install it."


def find_ytdlp_binary() -> Path | None:
    """Check for standalone yt-dlp binary in bundled and system paths."""
    candidates: list[Path] = []
    exe_name = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"

    # PyInstaller temporary and executable dirs
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "bin" / exe_name)
            candidates.append(Path(sys._MEIPASS) / exe_name)
        exe_parent = Path(sys.executable).parent
        candidates.append(exe_parent / "bin" / exe_name)
        candidates.append(exe_parent / exe_name)

    # Repository / project bin directory
    repo_bin = Path(__file__).resolve().parents[4] / "bin"
    candidates.append(repo_bin / exe_name)

    for c in candidates:
        if c.is_file():
            return c

    # System PATH
    found = shutil.which("yt-dlp") or (shutil.which("yt-dlp.exe") if sys.platform == "win32" else None)
    if found:
        return Path(found)

    return None


def get_default_base_command() -> list[str]:
    bin_path = find_ytdlp_binary()
    if bin_path is not None:
        return [str(bin_path)]
    return [sys.executable, "-m", "yt_dlp"]


def detect_ytdlp() -> tuple[bool, str | None, str | None]:
    """(available, version, message)"""
    bin_path = find_ytdlp_binary()
    if bin_path is not None:
        try:
            res = subprocess.run([str(bin_path), "--version"], capture_output=True, text=True, timeout=5.0, check=False)
            v = (res.stdout or "").strip()
            if v:
                return True, v, None
            return True, "standalone", None
        except Exception:
            return True, "standalone", None

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
    if any(k in text for k in ("sign in", "log in", "login", "private", "members", "premium", "subscri", "http error 401", "http error 403", "account authentication is required", "instagram api is not granting access")):
        return AppError(
            ErrorCode.MEDIA_NOT_AVAILABLE,
            "This media requires login or cookies. Add your cookies in Settings ⚙️ to download from this platform.",
            reason="auth_required",
        )
    if any(k in text for k in ("http error 404", "http error 410", "not found", "does not exist", "unavailable", "removed", "deleted")):
        return AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That media is no longer available at this address.", reason="not_found")
    if any(k in text for k in ("ip address is blocked", "statuscode: 10204", "10204", "slardarwaf", "tiktok block")):
        return AppError(
            ErrorCode.MEDIA_NOT_AVAILABLE,
            "TikTok restricted access from this network. Add your cookies in Settings ⚙️ or try again.",
            reason="ip_blocked",
        )
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
    ext = str(raw.get("ext") or "mp4").lower()
    if not _EXT.match(ext) or ext == "mhtml" or "storyboard" in str(raw.get("format_note") or "").lower():
        return None
    protocol = raw.get("protocol")
    if protocol is not None and protocol not in ALLOWED_PROTOCOLS:
        return None

    vcodec, acodec = raw.get("vcodec"), raw.get("acodec")
    height = _positive_int(raw.get("height"))
    has_video = (vcodec != "none" and (vcodec is not None or height is not None)) or ext in ("mp4", "webm", "mkv", "mov", "avi")
    has_audio = (acodec != "none") or ext in ("mp3", "m4a", "aac", "ogg", "opus", "wav", "flac")
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

    raw_formats = info.get("formats")
    if not raw_formats and (info.get("url") or info.get("protocol")):
        raw_formats = [info]

    formats = [f for f in (_normalize_format(r) for r in (raw_formats or [])) if f is not None]
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


def is_youtube_url(url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
        return any(
            host == d or host.endswith("." + d)
            for d in ("youtube.com", "youtu.be", "youtube-nocookie.com")
        )
    except Exception:
        return False


class YtDlpSource(MediaSource):
    id = "ytdlp"
    label = "Web media"

    def __init__(
        self,
        domains: frozenset[str],
        *,
        settings: Settings | None = None,
        runner: Runner | None = None,
        timeout: float = 60.0,
        base_command: list[str] | None = None,
    ) -> None:
        self._domains = frozenset(d.lower() for d in domains)
        self._settings = settings
        self._runner = runner or default_runner
        self._timeout = timeout
        self._base_command = list(base_command) if base_command else get_default_base_command()
        self._fallback_urls: dict[tuple[str, str], str] = {}

    def can_handle(self, url: ValidatedURL) -> bool:
        host = url.host
        domains = self._settings.source_domains if self._settings is not None else self._domains
        if "*" in domains or "all" in domains:
            return True
        return any(host == d or host.endswith("." + d) for d in domains)

    def _cookie_args(self) -> list[str]:
        cookies_file = self._settings.cookies_path if self._settings is not None else None
        if cookies_file and cookies_file.is_file():
            return ["--cookies", str(cookies_file)]
        default_file = Path("data/cookies.txt")
        if default_file.is_file():
            return ["--cookies", str(default_file)]
        return ["--no-cookies"]

    def _impersonate_args(self, url: str | None = None) -> list[str]:
        # Never impersonate desktop Chrome for YouTube: Google detects anomalous TLS/botguard fingerprints
        # on googlevideo/player API and responds with bot verification / HTTP 403 Forbidden.
        if url and is_youtube_url(url):
            return []
        if importlib.util.find_spec("curl_cffi") is not None:
            return ["--impersonate", "chrome"]
        return []

    def build_command(self, url: str) -> list[str]:
        # Argument list only. "--" ends option parsing so the URL can never be read as a flag.
        return [
            *self._base_command,
            "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-exec",
            *self._cookie_args(),
            *self._impersonate_args(url),
            "--dump-single-json", "--no-playlist", "--no-warnings", "--no-progress",
            "--socket-timeout", "15", "--retries", "2", "--extractor-retries", "2",
            "--", url,
        ]

    def _try_tiktok_fallback(self, url: str) -> MediaInfo | None:
        try:
            target_url = url
            if any(h in url for h in ("vt.tiktok.com", "vm.tiktok.com")):
                try:
                    req = urllib.request.Request(
                        url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        resolved = resp.geturl()
                        if "video" in resolved or "tiktok.com" in resolved:
                            target_url = resolved
                except Exception:
                    pass

            api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(target_url, safe='')}"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8", "replace"))

            if data.get("code") != 0 or not isinstance(data.get("data"), dict):
                return None

            info_data = data["data"]
            title = info_data.get("title") or "TikTok Video"
            title = title.strip()[:MAX_TITLE] if isinstance(title, str) and title.strip() else "TikTok Video"
            duration = _positive_int(info_data.get("duration"))
            cover = info_data.get("cover") or info_data.get("origin_cover")
            size = _positive_int(info_data.get("size"))

            formats: list[MediaFormat] = []
            play_url = info_data.get("play")
            if play_url and isinstance(play_url, str):
                formats.append(
                    MediaFormat(
                        id="tikwm_play",
                        type="video",
                        container="mp4",
                        resolution=None,
                        has_audio=True,
                        filesize=size,
                        filesize_approximate=False,
                        label="HD Video (No Watermark) · MP4",
                    )
                )
                self._fallback_urls[("tikwm_play", url)] = play_url

            music_url = info_data.get("music")
            if music_url and isinstance(music_url, str):
                formats.append(
                    MediaFormat(
                        id="tikwm_music",
                        type="audio",
                        container="mp3",
                        resolution=None,
                        has_audio=True,
                        filesize=None,
                        filesize_approximate=False,
                        label="Original Audio · MP3",
                    )
                )
                self._fallback_urls[("tikwm_music", url)] = music_url

            if not formats:
                return None

            logger.info("extracted TikTok media using resilient fallback", extra={"operation": "tiktok_fallback", "title": title})
            return MediaInfo(
                source_id=self.id,
                source_label=self.label,
                url=url,
                title=title,
                duration=duration,
                formats=tuple(formats),
                thumbnail_url=cover if isinstance(cover, str) and cover.startswith("https://") else None,
            )
        except Exception as exc:
            logger.warning("tiktok fallback extractor failed: %s", exc)
            return None

    def analyze(self, url: ValidatedURL) -> MediaInfo:
        available, _, message = detect_ytdlp()
        if not available:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, message or INSTALL_HINT, reason="ytdlp_missing")

        is_tiktok = any(url.host == d or url.host.endswith("." + d) for d in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"))

        code, out, err = self._runner(self.build_command(url.url), self._timeout)
        if code != 0:
            err_text = err.decode("utf-8", "replace")
            logger.warning(
                "extractor failed",
                extra={"operation": "ytdlp", "status": "failed", "reason": redact_text(err_text)[:300]},
            )
            if is_tiktok:
                fallback = self._try_tiktok_fallback(url.url)
                if fallback is not None:
                    return fallback
            raise map_error(err_text)
        if len(out) > MAX_OUTPUT_BYTES:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website returned more data than expected.", reason="output_too_large")
        try:
            info = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            if is_tiktok:
                fallback = self._try_tiktok_fallback(url.url)
                if fallback is not None:
                    return fallback
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website returned data in an unexpected format.", reason="bad_json") from None
        try:
            return normalize_info(info, source_id=self.id, source_label=self.label, url=url.url)
        except AppError:
            if is_tiktok:
                fallback = self._try_tiktok_fallback(url.url)
                if fallback is not None:
                    return fallback
            raise

    # ------------------------------------------------------------------ download

    def build_download_command(self, url: str, fmt_id: str, dest_dir: Path, part: int, ctx: DownloadContext) -> list[str]:
        if not _FORMAT_ID.match(fmt_id):  # defence in depth: ids are validated at analysis time too
            raise AppError(ErrorCode.FORMAT_NOT_AVAILABLE, "The selected format is no longer available.", reason="bad_format_id")
        # The output path is a yt-dlp *template*, so a literal "%" in our own directory must be escaped.
        template = str(dest_dir / f"part{part}").replace("%", "%%") + ".%(ext)s"
        command = [
            *self._base_command,
            "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-exec",
            *self._cookie_args(),
            *self._impersonate_args(url),
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

        target_url = url.url
        target_fmt_id = fmt.id
        if fmt.id.startswith("tikwm_"):
            stream_url = self._fallback_urls.get((fmt.id, url.url))
            if not stream_url:
                self._try_tiktok_fallback(url.url)
                stream_url = self._fallback_urls.get((fmt.id, url.url))
            if stream_url:
                target_url = stream_url
                target_fmt_id = "mp4" if fmt.type == "video" else "best"

        def on_line(line: str) -> None:
            progress = parse_progress_line(line)
            if progress is not None:
                ctx.on_progress(progress)

        env = controlled_env()
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        try:
            result = run_controlled(
                self.build_download_command(target_url, target_fmt_id, dest_dir, part, ctx),
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
