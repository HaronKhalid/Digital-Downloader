"""Outbound HTTP client for source adapters and downloads.

This is deliberately not a generic ``requests.get(user_url)``. Every hop:

* is validated with the SSRF rules in ``utils.urls``,
* connects to an IP that was validated (pinned), never re-resolving the name,
* verifies TLS against the *hostname* (SNI + certificate check) even though the
  socket is opened to the pinned IP,
* is limited in redirects, time and body size, and may not downgrade https to http.

Proxy environment variables are ignored on purpose (we open sockets ourselves).
"""

from __future__ import annotations

import errno
import http.client
import logging
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping
from urllib.parse import urlsplit

from ..core.errors import AppError, ErrorCode, OperationCancelled
from ..utils.urls import DEFAULT_ALLOWED_PORTS, Resolver, ValidatedURL, validate_redirect, validate_url

logger = logging.getLogger("app.http")

Connector = Callable[[str, int, float], socket.socket]
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
USER_AGENT = "PersonalMedia/0.1"
CHUNK_SIZE = 64 * 1024
PROGRESS_INTERVAL = 0.25  # seconds between progress callbacks


def error_for_status(status: int) -> AppError:
    """Categorized error for an unusable HTTP status."""
    if status in (401, 403):
        return AppError(
            ErrorCode.MEDIA_NOT_AVAILABLE,
            "This file needs a sign-in or special permission, so it can't be downloaded here.",
            reason=f"http_{status}",
        )
    if status in (404, 410):
        return AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That file is no longer available at this address.", reason=f"http_{status}")
    return AppError(ErrorCode.SOURCE_UNAVAILABLE, "The website couldn't provide that file right now.", reason=f"http_{status}")


def _default_connector(ip: str, port: int, timeout: float) -> socket.socket:
    return socket.create_connection((ip, port), timeout=timeout)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, ip: str, connector: Connector, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._ip = ip
        self._connector = connector

    def connect(self) -> None:
        self.sock = self._connector(self._ip, self.port, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int, *, ip: str, connector: Connector, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip
        self._connector = connector
        self._tls_context = context

    def connect(self) -> None:
        raw = self._connector(self._ip, self.port, self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]  # lower-cased names
    body: bytes
    url: str  # final URL after redirects


@dataclass(frozen=True)
class TransferProgress:
    downloaded: int
    total: int | None
    speed: float | None  # bytes per second
    eta: float | None  # seconds


ProgressCallback = Callable[[TransferProgress], None]


class SafeHttpClient:
    def __init__(
        self,
        *,
        allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
        resolver: Resolver | None = None,
        connector: Connector | None = None,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = 10.0,
        max_redirects: int = 3,
    ) -> None:
        self._ports = allowed_ports
        self._resolver = resolver
        self._connector = connector or _default_connector
        self._ssl = ssl_context or ssl.create_default_context()
        self._timeout = timeout
        self._max_redirects = max_redirects

    # ------------------------------------------------------------ plumbing

    def _follow(self, method: str, url: str, headers: Mapping[str, str]):
        """Resolve redirects (each hop validated) and return an *open* (conn, response, final target)."""
        if method not in ("GET", "HEAD"):
            raise ValueError("Only GET and HEAD are supported.")
        current = validate_url(url, allowed_ports=self._ports, resolver=self._resolver)
        for hop in range(self._max_redirects + 1):
            conn, raw = self._open(method, current, headers)
            location = raw.getheader("location")
            if raw.status in REDIRECT_STATUSES and location:
                conn.close()
                if hop == self._max_redirects:
                    raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The link redirected too many times.", reason="redirect_limit")
                target = validate_redirect(current.url, location, allowed_ports=self._ports, resolver=self._resolver)
                if current.scheme == "https" and target.scheme == "http":
                    raise AppError(
                        ErrorCode.SOURCE_UNAVAILABLE,
                        "The link tried to switch from a secure to an insecure connection.",
                        reason="https_downgrade",
                    )
                current = target
                continue
            return conn, raw, current
        raise AssertionError("unreachable")  # pragma: no cover

    def _open(self, method: str, target: ValidatedURL, extra: Mapping[str, str]):
        parts = urlsplit(target.url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
            **extra,
        }
        timed_out = False
        for ip in target.resolved_ips:
            if target.scheme == "https":
                conn: http.client.HTTPConnection = _PinnedHTTPSConnection(
                    target.host, target.port, ip=ip, connector=self._connector,
                    timeout=self._timeout, context=self._ssl,
                )
            else:
                conn = _PinnedHTTPConnection(
                    target.host, target.port, ip=ip, connector=self._connector, timeout=self._timeout
                )
            try:
                conn.request(method, path, headers=headers)
                return conn, conn.getresponse()
            except TimeoutError:
                timed_out = True
                conn.close()
            except (OSError, http.client.HTTPException):
                conn.close()  # try the next validated address
        if timed_out:
            raise AppError(ErrorCode.TIMEOUT, "The website took too long to respond.", reason="timeout")
        raise AppError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "Couldn't connect to the website. Check your connection and the URL.",
            reason="connect_failed",
        )

    # ------------------------------------------------------------ public API

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        max_body: int = 0,
    ) -> HttpResponse:
        """Perform a request. ``max_body=0`` means the body is not read at all."""
        conn, raw, final = self._follow(method, url, headers or {})
        try:
            body = b""
            if method == "GET" and max_body > 0:
                try:
                    body = raw.read(max_body + 1)
                except TimeoutError:
                    raise AppError(ErrorCode.TIMEOUT, "The website took too long to respond.", reason="read_timeout") from None
                except (OSError, http.client.HTTPException):
                    raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The connection was lost.", reason="connection_lost") from None
                if len(body) > max_body:
                    raise AppError(
                        ErrorCode.MEDIA_NOT_AVAILABLE, "The response was larger than expected.", reason="body_too_large"
                    )
            return HttpResponse(raw.status, {k.lower(): v for k, v in raw.getheaders()}, body, final.url)
        finally:
            conn.close()

    @contextmanager
    def stream(self, url: str, *, headers: Mapping[str, str] | None = None) -> Iterator[tuple[http.client.HTTPResponse, ValidatedURL]]:
        """GET with the same protections as ``request``; yields the open response for incremental reading."""
        conn, raw, final = self._follow("GET", url, headers or {})
        try:
            yield raw, final
        finally:
            conn.close()

    def download_file(
        self,
        url: str,
        dest: Path,
        *,
        max_bytes: int,
        cancel: threading.Event | None = None,
        on_progress: ProgressCallback | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> int:
        """Stream ``url`` to ``dest`` (which must not exist). Returns the number of bytes written.

        Never overwrites, enforces ``max_bytes`` even when the server lies about Content-Length,
        and treats a short body as a lost connection rather than a finished download.
        """
        with self.stream(url, headers=headers) as (raw, _final):
            if raw.status != 200:
                raise error_for_status(raw.status)
            length = raw.getheader("content-length", "")
            total = int(length) if length.isdigit() else None
            if total is not None and total > max_bytes:
                raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That file is larger than the maximum size allowed.", reason="too_large")

            received = 0
            started = last_report = last_rate_time = time.monotonic()
            last_rate_bytes = 0
            speed: float | None = None

            def report(force: bool = False) -> None:
                nonlocal last_report, last_rate_time, last_rate_bytes, speed
                now = time.monotonic()
                if not force and now - last_report < PROGRESS_INTERVAL:
                    return
                if now - last_rate_time >= 0.5:
                    instant = (received - last_rate_bytes) / (now - last_rate_time)
                    speed = instant if speed is None else 0.7 * speed + 0.3 * instant
                    last_rate_time, last_rate_bytes = now, received
                last_report = now
                eta = (total - received) / speed if total is not None and speed and speed > 0 else None
                if on_progress:
                    on_progress(TransferProgress(received, total, speed, eta))

            with open(dest, "xb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise OperationCancelled
                    try:
                        chunk = raw.read(CHUNK_SIZE)
                    except TimeoutError:
                        raise AppError(ErrorCode.TIMEOUT, "The website stopped sending data.", reason="read_timeout") from None
                    except (OSError, http.client.HTTPException):
                        raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The connection was lost.", reason="connection_lost") from None
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_bytes:
                        raise AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "That file is larger than the maximum size allowed.", reason="too_large")
                    try:
                        out.write(chunk)
                    except OSError as exc:
                        if exc.errno == errno.ENOSPC:
                            raise AppError(ErrorCode.DISK_SPACE_LOW, "There isn't enough free disk space to finish this download.", reason="enospc") from None
                        raise AppError(ErrorCode.PERMISSION_DENIED, "The file couldn't be written to disk.", reason="write_failed") from None
                    report()

            if total is not None and received != total:
                raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The connection was lost before the download finished.", reason="connection_lost")
            report(force=True)
            return received
