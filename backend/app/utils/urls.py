"""URL validation, normalization and SSRF protection.

Every URL that reaches the backend is untrusted. Validation happens in two layers:

1. Syntax layer (no network): scheme, credentials, port, host form, IP literals.
2. Destination layer (DNS): every address the host resolves to must be public.

Callers that go on to make network requests must connect to the addresses in
``ValidatedURL.resolved_ips`` (pinning them) and must re-run validation on every
redirect via :func:`validate_redirect`. Validating once and then letting an HTTP
client re-resolve the name would leave a DNS-rebinding gap.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit

from ..core.errors import AppError, ErrorCode

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_ALLOWED_PORTS = frozenset({80, 443})
_DEFAULT_PORTS = {"http": 80, "https": 443}

BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "instance-data",
        "kubernetes.default.svc",
    }
)
BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".corp",
    ".intranet",
    ".home.arpa",
)

_HOST_CHARS = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")
# Browsers treat a host whose last label is numeric/hex as an IPv4 address
# (e.g. 2130706433, 0x7f.1, 127.1). We refuse every such form that is not a
# canonical dotted quad, so no parser disagreement can smuggle an address through.
_NUMERIC_LABEL = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

_MESSAGES = {
    "empty": "Paste a media URL to begin.",
    "too_long": "That URL is too long to be a valid media link.",
    "control_chars": "The URL contains characters that are not allowed.",
    "malformed": "That doesn't look like a valid web address.",
    "bad_scheme": "Only http:// and https:// links are supported.",
    "no_host": "The URL is missing a website address.",
    "credentials": "URLs that contain a username or password are not supported.",
    "bad_port": "The URL contains an invalid port number.",
    "port_not_allowed": "That port is not allowed. Only standard web ports are supported.",
    "bad_host": "That website address isn't valid.",
    "ambiguous_ip": "Numeric addresses must be written in standard dotted form.",
    "blocked_ip": "That address points to this computer or a private network, so it can't be used.",
    "blocked_host": "That address points to this computer or a private network, so it can't be used.",
    "dns_failure": "The website address could not be found. Check the URL and your connection.",
}


class UrlValidationError(AppError):
    """Raised when a URL fails validation. ``reason`` is a stable machine-readable tag."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            ErrorCode.INVALID_URL,
            _MESSAGES.get(reason, "That URL can't be used."),
            status_code=400,
            reason=reason,
        )


@dataclass(frozen=True)
class ValidatedURL:
    url: str  # normalized, fragment removed
    scheme: str
    host: str
    port: int
    resolved_ips: tuple[str, ...]  # empty when resolution was skipped


Resolver = Callable[..., Iterable[tuple]]


# --------------------------------------------------------------------------- #
# IP classification
# --------------------------------------------------------------------------- #


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv4 addresses that an IPv6 address can tunnel to (mapped, 6to4, Teredo, NAT64)."""
    found: list[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)  # (server, client): check both
    if ip in _NAT64:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def _is_blocked_single(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the address is not a plain public unicast address (including tunneled forms)."""
    if _is_blocked_single(ip):
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        return any(_is_blocked_single(v4) for v4 in _embedded_ipv4(ip))
    return False


# --------------------------------------------------------------------------- #
# Syntax layer
# --------------------------------------------------------------------------- #


def _parse(raw: object, allowed_ports: frozenset[int]) -> tuple[str, str, int, str, str]:
    """Return (scheme, host, port, path, query) or raise UrlValidationError."""
    if not isinstance(raw, str) or not raw.strip():
        raise UrlValidationError("empty")
    text = raw.strip()
    if len(text) > MAX_URL_LENGTH:
        raise UrlValidationError("too_long")
    # Whitespace, control characters and backslashes make parsers disagree
    # (browsers treat "\" as "/"), which is the root of many SSRF bypasses.
    if any(ord(c) <= 0x20 or ord(c) == 0x7F for c in text) or "\\" in text:
        raise UrlValidationError("control_chars")

    try:
        parts = urlsplit(text)
    except ValueError:
        raise UrlValidationError("malformed") from None

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlValidationError("bad_scheme")
    if not parts.netloc:
        raise UrlValidationError("no_host")
    if "@" in parts.netloc:
        raise UrlValidationError("credentials")

    try:
        port = parts.port
    except ValueError:
        raise UrlValidationError("bad_port") from None
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if not 1 <= port <= 65535:
        raise UrlValidationError("bad_port")
    if port not in allowed_ports:
        raise UrlValidationError("port_not_allowed")

    host = parts.hostname
    if not host:
        raise UrlValidationError("no_host")
    host = host.rstrip(".").lower()
    if not host:
        raise UrlValidationError("no_host")
    return scheme, host, port, parts.path or "/", parts.query


def _classify_host(host: str) -> str:
    """Normalize ``host`` and raise if it is syntactically unsafe.

    Returns the normalized host (IDNA-encoded for names, canonical for IP literals).
    """
    if "%" in host:  # IPv6 zone ids and percent-encoded hosts
        raise UrlValidationError("bad_host")

    if ":" in host:  # IPv6 literal (urlsplit already stripped the brackets)
        try:
            ip6 = ipaddress.IPv6Address(host)
        except ValueError:
            raise UrlValidationError("bad_host") from None
        if is_blocked_ip(ip6):
            raise UrlValidationError("blocked_ip")
        return str(ip6)

    try:
        ip4 = ipaddress.IPv4Address(host)
    except ValueError:
        ip4 = None
    if ip4 is not None:
        if is_blocked_ip(ip4):
            raise UrlValidationError("blocked_ip")
        return str(ip4)

    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise UrlValidationError("bad_host") from None
    if not _HOST_CHARS.match(ascii_host) or len(ascii_host) > 253:
        raise UrlValidationError("bad_host")
    if _NUMERIC_LABEL.match(ascii_host.rsplit(".", 1)[-1]):
        raise UrlValidationError("ambiguous_ip")
    if ascii_host in BLOCKED_HOSTNAMES or ascii_host.endswith(BLOCKED_SUFFIXES):
        raise UrlValidationError("blocked_host")
    if "." not in ascii_host:  # single-label names resolve via local search domains
        raise UrlValidationError("blocked_host")
    return ascii_host


def _format_url(scheme: str, host: str, port: int, path: str, query: str) -> str:
    netloc = f"[{host}]" if ":" in host else host
    if port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


# --------------------------------------------------------------------------- #
# Destination layer
# --------------------------------------------------------------------------- #


def resolve_public_addresses(host: str, port: int, resolver: Resolver | None = None) -> tuple[str, ...]:
    """Resolve ``host`` and require *every* answer to be a public address.

    Rejecting the whole name when any answer is internal defeats mixed-answer
    DNS tricks. The returned addresses should be used to make the connection.
    """
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        return (host,)

    resolve = resolver or socket.getaddrinfo
    try:
        infos = list(resolve(host, port, type=socket.SOCK_STREAM))
    except (OSError, UnicodeError):
        raise UrlValidationError("dns_failure") from None

    addresses: list[str] = []
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise UrlValidationError("dns_failure") from None
        if is_blocked_ip(ip):
            raise UrlValidationError("blocked_ip")
        if addr not in addresses:
            addresses.append(addr)
    if not addresses:
        raise UrlValidationError("dns_failure")
    return tuple(addresses)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def validate_url(
    raw: object,
    *,
    allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    resolve: bool = True,
    resolver: Resolver | None = None,
) -> ValidatedURL:
    """Validate and normalize an untrusted URL. Raises :class:`UrlValidationError`."""
    scheme, host, port, path, query = _parse(raw, allowed_ports)
    host = _classify_host(host)
    ips = resolve_public_addresses(host, port, resolver) if resolve else ()
    return ValidatedURL(
        url=_format_url(scheme, host, port, path, query),
        scheme=scheme,
        host=host,
        port=port,
        resolved_ips=ips,
    )


def validate_redirect(
    current_url: str,
    location: str,
    *,
    allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    resolver: Resolver | None = None,
) -> ValidatedURL:
    """Validate a redirect target (absolute or relative) exactly like a fresh URL."""
    return validate_url(
        urljoin(current_url, location), allowed_ports=allowed_ports, resolver=resolver
    )


# --------------------------------------------------------------------------- #
# Log redaction
# --------------------------------------------------------------------------- #

_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Drop credentials, query string and fragment so URLs are safe to log."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not parts.scheme or not host:
            return "<invalid-url>"
        netloc = f"[{host}]" if ":" in host else host
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        redacted = f"{parts.scheme}://{netloc}{parts.path}"
        return redacted + ("?<redacted>" if parts.query else "")
    except ValueError:
        return "<invalid-url>"


def redact_text(text: str) -> str:
    """Redact every URL found inside free text (log messages, exception strings)."""
    return _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0)), text)
