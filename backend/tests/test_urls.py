import socket

import pytest

from backend.app.core.errors import ErrorCode
from backend.app.utils.urls import (
    UrlValidationError,
    redact_text,
    redact_url,
    validate_redirect,
    validate_url,
)

from .conftest import make_resolver

PUBLIC = make_resolver("93.184.216.34")


def reason_of(url, **kw):
    with pytest.raises(UrlValidationError) as exc:
        validate_url(url, resolver=kw.pop("resolver", PUBLIC), **kw)
    assert exc.value.code is ErrorCode.INVALID_URL
    return exc.value.reason


# ---------------------------------------------------------------- valid URLs


def test_https_url_is_accepted_and_normalized():
    v = validate_url("  HTTPS://Valid.Example/watch?v=1#frag ", resolver=PUBLIC)
    assert v.url == "https://valid.example/watch?v=1"
    assert (v.scheme, v.host, v.port) == ("https", "valid.example", 443)
    assert v.resolved_ips == ("93.184.216.34",)


def test_http_url_is_accepted():
    assert validate_url("http://valid.example", resolver=PUBLIC).url == "http://valid.example/"


def test_public_ip_literal_is_accepted_without_dns():
    v = validate_url("https://93.184.216.34/x", resolver=lambda *a, **k: pytest.fail("no DNS expected"))
    assert v.resolved_ips == ("93.184.216.34",)


def test_resolve_false_skips_dns():
    v = validate_url("https://valid.example/", resolve=False, resolver=lambda *a, **k: pytest.fail("no DNS"))
    assert v.resolved_ips == ()


def test_idna_host_is_normalized():
    assert validate_url("https://bücher.example/", resolver=PUBLIC).host == "xn--bcher-kva.example"


# ------------------------------------------------------------ bad schemes


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "javascript:test",
        "data:text/plain,hello",
        "ftp://example.com/file",
        "gopher://example.com/",
        "//example.com/path",
        "example.com/path",
        "https:example.com",
    ],
)
def test_non_http_schemes_rejected(url):
    assert reason_of(url) in {"bad_scheme", "no_host"}


@pytest.mark.parametrize("url", ["", "   ", None, 123, [], {}])
def test_empty_or_non_string_rejected(url):
    assert reason_of(url) == "empty"


def test_overlong_url_rejected():
    assert reason_of("https://valid.example/" + "a" * 3000) == "too_long"


@pytest.mark.parametrize(
    "url",
    [
        "https://valid.example/a b",
        "https://valid.example/\r\nHost: evil.example",
        "https://valid.example/\x00",
        "https://valid.example/\tx",
        "https://valid.example\\@127.0.0.1/",
        "http://valid.example\\admin",
    ],
)
def test_whitespace_control_chars_and_backslashes_rejected(url):
    assert reason_of(url) == "control_chars"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@valid.example/",
        "https://valid.example@127.0.0.1/",
        "https://@valid.example/",
    ],
)
def test_embedded_credentials_rejected(url):
    assert reason_of(url) == "credentials"


@pytest.mark.parametrize("url", ["https://", "https:///path", "https://:443/"])
def test_missing_host_rejected(url):
    assert reason_of(url) in {"no_host", "bad_host"}


# --------------------------------------------------------------------- ports


@pytest.mark.parametrize("url", ["http://valid.example:22/", "http://valid.example:8080/", "http://valid.example:6379/"])
def test_non_web_ports_rejected_by_default(url):
    assert reason_of(url) == "port_not_allowed"


def test_extra_port_can_be_allowed_explicitly():
    v = validate_url("http://valid.example:8080/", allowed_ports=frozenset({80, 443, 8080}), resolver=PUBLIC)
    assert v.url == "http://valid.example:8080/"


@pytest.mark.parametrize("url", ["http://valid.example:99999/", "http://valid.example:0/", "http://valid.example:abc/"])
def test_invalid_ports_rejected(url):
    assert reason_of(url) == "bad_port"


# --------------------------------------------------------------------- SSRF


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.255.255.254/",
        "http://localhost/",
        "http://LOCALHOST./",
        "http://foo.localhost/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::]/",
        "http://10.0.0.5/",
        "http://10.255.255.255/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[fd12:3456::1]/",
        "http://[ff02::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:7f00:1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[2002:7f00:1::]/",
        "http://metadata.google.internal/",
        "http://printer.local/",
        "http://nas.lan/",
        "http://intranet/",
    ],
)
def test_internal_destinations_rejected(url):
    assert reason_of(url) in {"blocked_ip", "blocked_host"}


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f000001/",  # hex
        "http://0x7f.0.0.1/",
        "http://0177.0.0.1/",  # octal
        "http://127.1/",
        "http://127.0.1/",
        "http://017700000001/",
        "http://0300.0250.0.1/",  # octal 192.168.0.1
    ],
)
def test_alternate_ip_encodings_rejected(url):
    assert reason_of(url) in {"ambiguous_ip", "bad_host", "blocked_ip"}


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.0.7", "169.254.169.254", "::1", "::ffff:127.0.0.1", "fd00::1"])
def test_hostname_resolving_to_internal_address_rejected(ip):
    assert reason_of("https://innocent.example/", resolver=make_resolver(ip)) == "blocked_ip"


def test_mixed_dns_answers_rejected_if_any_is_internal():
    assert reason_of("https://innocent.example/", resolver=make_resolver("93.184.216.34", "10.0.0.1")) == "blocked_ip"


def test_dns_failure_is_reported():
    def failing(*a, **k):
        raise socket.gaierror("nope")

    assert reason_of("https://nonexistent.example/", resolver=failing) == "dns_failure"


def test_empty_dns_answer_rejected():
    assert reason_of("https://innocent.example/", resolver=lambda *a, **k: []) == "dns_failure"


def test_resolved_ips_are_returned_for_pinning():
    v = validate_url("https://innocent.example/", resolver=make_resolver("93.184.216.34", "2606:2800:220:1::1"))
    assert v.resolved_ips == ("93.184.216.34", "2606:2800:220:1::1")


# ----------------------------------------------------------------- redirects


def test_redirect_to_internal_address_rejected():
    with pytest.raises(UrlValidationError) as exc:
        validate_redirect("https://valid.example/a", "http://127.0.0.1/admin", resolver=PUBLIC)
    assert exc.value.reason == "blocked_ip"


def test_redirect_to_metadata_endpoint_rejected():
    with pytest.raises(UrlValidationError):
        validate_redirect("https://valid.example/a", "http://169.254.169.254/latest/", resolver=PUBLIC)


def test_relative_redirect_resolved_and_revalidated():
    assert validate_redirect("https://valid.example/a/b", "../c?x=1", resolver=PUBLIC).url == "https://valid.example/c?x=1"


def test_redirect_to_non_http_scheme_rejected():
    with pytest.raises(UrlValidationError):
        validate_redirect("https://valid.example/a", "file:///etc/passwd", resolver=PUBLIC)


# ------------------------------------------------------------------- logging


def test_redact_url_removes_credentials_query_and_fragment():
    out = redact_url("https://user:secret@example.com/path/x?token=abc&sig=zzz#frag")
    assert out == "https://example.com/path/x?<redacted>"
    assert "secret" not in out and "abc" not in out


def test_redact_url_handles_garbage():
    assert redact_url("not a url") == "<invalid-url>"


def test_redact_text_finds_urls_inside_messages():
    out = redact_text("failed to fetch https://example.com/v?sig=SECRET123 after 2s")
    assert "SECRET123" not in out and "https://example.com/v?<redacted>" in out


# ------------------------------------------- defence in depth (stdlib-independent)


def test_tunnelled_ipv4_is_blocked_even_if_stdlib_calls_the_wrapper_global(monkeypatch):
    """Our own unwrapping must catch mapped/6to4/Teredo/NAT64 forms regardless of how a
    given Python version classifies the IPv6 wrapper range."""
    import ipaddress

    from backend.app.utils import urls

    def only_blocks_ipv4_loopback(ip):  # a stdlib that "forgets" tunnel ranges
        return isinstance(ip, ipaddress.IPv4Address) and (ip.is_loopback or ip.is_private)

    monkeypatch.setattr(urls, "_is_blocked_single", only_blocks_ipv4_loopback)
    for text in ["::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "2002:c0a8:101::"]:
        assert urls.is_blocked_ip(ipaddress.IPv6Address(text)), text
    assert not urls.is_blocked_ip(ipaddress.IPv6Address("::ffff:93.184.216.34"))
