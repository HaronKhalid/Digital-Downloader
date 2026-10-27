"""In-app yt-dlp updater.

Sites change constantly, so a downloader whose yt-dlp is frozen at build time stops working. This
service downloads the official standalone yt-dlp binary from the project's GitHub releases into the
user's data folder, where it takes priority over the bundled copy.

Safety rules:
* Only HTTPS, and only github.com / githubusercontent.com (also enforced on every redirect).
* The binary is verified against the release's ``SHA2-256SUMS`` file before it is used.
* The new binary must run and report the release version before it replaces the old one.
* The swap is atomic (``os.replace``); a failed update leaves the working binary untouched.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from ..core.errors import AppError, ErrorCode

logger = logging.getLogger("app.ytdlp.update")

RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
ALLOWED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")
MAX_BINARY_BYTES = 80 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
_VERSION = re.compile(r"^\d{4}\.\d{2}\.\d{2}(?:\.\d+)?$")

Fetch = Callable[[str, int], bytes]


def asset_name(system: str | None = None, machine: str | None = None) -> str | None:
    """Name of the official standalone binary for this machine, or None if unsupported."""
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine()).lower()
    if system.startswith("win"):
        return "yt-dlp.exe"
    if system.startswith("linux"):
        return "yt-dlp_linux_aarch64" if machine in ("aarch64", "arm64") else "yt-dlp_linux"
    return None


def binary_name() -> str:
    return "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"


def _host_allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_allowed(newurl):
            raise urllib.error.URLError("redirect to a host that is not allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_fetch(url: str, max_bytes: int) -> bytes:
    if not _host_allowed(url):
        raise AppError(ErrorCode.PERMISSION_DENIED, "Update source is not allowed.", reason="host_not_allowed")
    opener = urllib.request.build_opener(_CheckedRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": "DigitalDownloader-updater", "Accept": "*/*"})
    with opener.open(request, timeout=60) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise AppError(ErrorCode.DOWNLOAD_FAILED, "The update file is larger than expected.", reason="too_large")
    return data


def parse_sums(text: str) -> dict[str, str]:
    """Parse ``<sha256>  <filename>`` lines."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def version_tuple(version: str | None) -> tuple[int, ...] | None:
    if not version or not _VERSION.match(version):
        return None
    return tuple(int(p) for p in version.split("."))


class YtDlpUpdater:
    def __init__(
        self,
        install_dir: Path,
        *,
        current_version: Callable[[], str | None],
        fetch: Fetch = default_fetch,
        verify_runner: Callable[[Path], str] | None = None,
    ) -> None:
        self._dir = Path(install_dir)
        self._current = current_version
        self._fetch = fetch
        self._verify = verify_runner or self._run_version
        self._lock = threading.Lock()

    @property
    def target(self) -> Path:
        return self._dir / binary_name()

    @staticmethod
    def _run_version(path: Path) -> str:
        kwargs: dict = {"capture_output": True, "text": True, "timeout": 30, "check": False, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        done = subprocess.run([str(path), "--version"], **kwargs)
        return (done.stdout or "").strip()

    # ------------------------------------------------------------------ lookup

    def _latest_release(self) -> tuple[str, dict[str, str]]:
        try:
            raw = self._fetch(RELEASE_API, MAX_TEXT_BYTES)
            data = json.loads(raw.decode("utf-8", "replace"))
        except AppError:
            raise
        except Exception:
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "Could not check for updates. Check your connection.", reason="update_check_failed") from None
        tag = data.get("tag_name") if isinstance(data, dict) else None
        if not isinstance(tag, str) or not _VERSION.match(tag):
            raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The update service returned unexpected data.", reason="bad_release")
        assets = {
            a["name"]: a["browser_download_url"]
            for a in data.get("assets", [])
            if isinstance(a, dict) and isinstance(a.get("name"), str) and isinstance(a.get("browser_download_url"), str)
        }
        return tag, assets

    def check(self) -> dict:
        supported = asset_name() is not None
        current = self._current()
        tag, _ = self._latest_release()
        cur_t, new_t = version_tuple(current), version_tuple(tag)
        available = supported and (new_t is not None and (cur_t is None or new_t > cur_t))
        return {"current": current, "latest": tag, "update_available": available, "supported": supported}

    # ------------------------------------------------------------------ update

    def update(self) -> dict:
        name = asset_name()
        if name is None:
            raise AppError(ErrorCode.UNSUPPORTED_SOURCE, "In-app updates are not available on this system.", reason="unsupported_platform")
        if not self._lock.acquire(blocking=False):
            raise AppError(ErrorCode.INVALID_REQUEST, "An update is already running.", status_code=409, reason="busy")
        try:
            previous = self._current()
            tag, assets = self._latest_release()
            binary_url, sums_url = assets.get(name), assets.get("SHA2-256SUMS")
            if not binary_url or not sums_url:
                raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The release does not contain the expected files.", reason="missing_assets")
            for url in (binary_url, sums_url):
                if not _host_allowed(url):
                    raise AppError(ErrorCode.PERMISSION_DENIED, "Update source is not allowed.", reason="host_not_allowed")

            try:
                sums = parse_sums(self._fetch(sums_url, MAX_TEXT_BYTES).decode("utf-8", "replace"))
                binary = self._fetch(binary_url, MAX_BINARY_BYTES)
            except AppError:
                raise
            except Exception:
                raise AppError(ErrorCode.DOWNLOAD_FAILED, "The update could not be downloaded.", reason="download_failed") from None

            expected = sums.get(name)
            actual = hashlib.sha256(binary).hexdigest()
            if not expected or not hmac.compare_digest(expected, actual):
                logger.error("yt-dlp update checksum mismatch", extra={"operation": "ytdlp_update", "status": "rejected"})
                raise AppError(ErrorCode.DOWNLOAD_FAILED, "The update failed its integrity check and was discarded.", reason="checksum_mismatch")

            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".yt-dlp-", suffix=".new", dir=self._dir)
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(binary)
                tmp.chmod(0o755)
                # Windows can only run files with an .exe suffix, so verify a correctly named copy.
                runnable = tmp.with_suffix(".exe") if sys.platform == "win32" else tmp
                if runnable != tmp:
                    tmp.replace(runnable)
                    tmp = runnable
                try:
                    reported = self._verify(tmp)
                except Exception:
                    reported = ""
                if reported != tag:
                    raise AppError(ErrorCode.DOWNLOAD_FAILED, "The downloaded update did not start correctly and was discarded.", reason="verify_failed")
                try:
                    os.replace(tmp, self.target)
                except PermissionError:
                    raise AppError(ErrorCode.INVALID_REQUEST, "The extractor is in use. Wait for downloads to finish and try again.", status_code=409, reason="in_use") from None
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            logger.info("yt-dlp updated", extra={"operation": "ytdlp_update", "status": tag})
            return {"previous": previous, "installed": tag}
        finally:
            self._lock.release()
