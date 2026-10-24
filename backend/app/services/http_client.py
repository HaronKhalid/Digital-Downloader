"""Outbound HTTP client for source adapters.

This is deliberately not a generic ``requests.get(user_url)``. Every hop:

* is validated with the SSRF rules in ``utils.urls``,
* connects to an IP that was validated (pinned), never re-resolving the name,
* verifies TLS against the *hostname* (SNI + certificate check) even though the
  socket is opened to the pinned IP,
* is limited in redirects, time and body size, and may not downgrade https to http.

Proxy environment variables are ignored on purpose (we open sockets ourselves).
"""

from __future__ import annotations

import http.client
import logging
import socket
import ssl
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlsplit

from ..core.errors import AppError, ErrorCode
from ..utils.urls import DEFAULT_ALLOWED_PORTS, Resolver, ValidatedURL, validate_redirect, validate_url

logger = logging.getLogger("app.http")

Connector = Callable[[str, int, float], socket.socket]
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
USER_AGENT = "PersonalMedia/0.1"


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

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        max_body: int = 0,
    ) -> HttpResponse:
        """Perform a request. ``max_body=0`` means the body is not read at all."""
        if method not in ("GET", "HEAD"):
            raise ValueError("Only GET and HEAD are supported.")
        current = validate_url(url, allowed_ports=self._ports, resolver=self._resolver)
        for hop in range(self._max_redirects + 1):
            response = self._send(method, current, headers or {}, max_body)
            location = response.headers.get("location")
            if response.status in REDIRECT_STATUSES and location:
                if hop == self._max_redirects:
                    raise AppError(ErrorCode.SOURCE_UNAVAILABLE, "The link redirected too many times.", reason="redirect_limit")
                target = validate_redirect(
                    current.url, location, allowed_ports=self._ports, resolver=self._resolver
                )
                if current.scheme == "https" and target.scheme == "http":
                    raise AppError(
                        ErrorCode.SOURCE_UNAVAILABLE,
                        "The link tried to switch from a secure to an insecure connection.",
                        reason="https_downgrade",
                    )
                current = target
                continue
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    def _send(self, method: str, target: ValidatedURL, extra: Mapping[str, str], max_body: int) -> HttpResponse:
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
                raw = conn.getresponse()
                body = b""
                if method == "GET" and max_body > 0:
                    body = raw.read(max_body + 1)
                    if len(body) > max_body:
                        raise AppError(
                            ErrorCode.MEDIA_NOT_AVAILABLE, "The response was larger than expected.", reason="body_too_large"
                        )
                return HttpResponse(raw.status, {k.lower(): v for k, v in raw.getheaders()}, body, target.url)
            except TimeoutError:
                timed_out = True
            except (OSError, http.client.HTTPException):
                pass  # try the next validated address
            finally:
                conn.close()
        if timed_out:
            raise AppError(ErrorCode.TIMEOUT, "The website took too long to respond.", reason="timeout")
        raise AppError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "Couldn't connect to the website. Check your connection and the URL.",
            reason="connect_failed",
        )
