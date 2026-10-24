import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.app.core.errors import AppError, ErrorCode
from backend.app.services.http_client import SafeHttpClient
from backend.app.utils.urls import UrlValidationError

from .conftest import make_resolver

PUBLIC_IP = "93.184.216.34"


class Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):  # silence
        pass

    def _respond(self):
        Handler.seen.append({"method": self.command, "path": self.path, "host": self.headers.get("Host")})
        routes = self.server.routes
        status, headers, body = routes.get(self.path, (404, {}, b"nope"))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_HEAD = _respond


def _serve(routes, tls_context=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.routes = routes
    if tls_context:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return server


@pytest.fixture(autouse=True)
def _reset():
    Handler.seen = []


@pytest.fixture
def routes():
    return {
        "/ok": (200, {"Content-Type": "video/mp4"}, b"hello"),
        "/redir": (302, {"Location": "/ok"}, b""),
        "/to-internal": (302, {"Location": "http://127.0.0.1/admin"}, b""),
        "/to-metadata": (301, {"Location": "http://169.254.169.254/latest/"}, b""),
        "/to-file": (302, {"Location": "file:///etc/passwd"}, b""),
        "/loop": (302, {"Location": "/loop"}, b""),
        "/big": (200, {}, b"x" * 5000),
    }


@pytest.fixture
def server(routes):
    s = _serve(routes)
    yield s
    s.shutdown()


def make_client(server, *ips, calls=None, **kw):
    port = server.server_address[1]

    def connector(ip, _port, timeout):
        if calls is not None:
            calls.append((ip, _port))
        return socket.create_connection(("127.0.0.1", port), timeout=timeout)

    return SafeHttpClient(resolver=make_resolver(*(ips or (PUBLIC_IP,))), connector=connector, **kw)


# ------------------------------------------------------------------ basics


def test_get_returns_status_headers_body(server):
    r = make_client(server).request("GET", "http://valid.example/ok", max_body=100)
    assert r.status == 200 and r.body == b"hello" and r.headers["content-type"] == "video/mp4"


def test_head_and_zero_max_body_do_not_read_body(server):
    c = make_client(server)
    assert c.request("HEAD", "http://valid.example/ok").body == b""
    assert c.request("GET", "http://valid.example/ok").body == b""


def test_only_get_and_head_are_allowed(server):
    with pytest.raises(ValueError):
        make_client(server).request("POST", "http://valid.example/ok")


def test_oversized_body_is_refused(server):
    with pytest.raises(AppError) as exc:
        make_client(server).request("GET", "http://valid.example/big", max_body=100)
    assert exc.value.code is ErrorCode.MEDIA_NOT_AVAILABLE


# ------------------------------------------------------- pinning & SSRF


def test_connects_to_validated_ip_not_hostname_and_sends_host_header(server):
    calls = []
    make_client(server, calls=calls).request("GET", "http://valid.example/ok")
    assert calls == [(PUBLIC_IP, 80)]
    assert Handler.seen[0]["host"] == "valid.example"


def test_internal_dns_answer_is_refused_before_any_connection(server):
    calls = []
    client = make_client(server, "10.0.0.1", calls=calls)
    with pytest.raises(UrlValidationError):
        client.request("GET", "http://valid.example/ok")
    assert calls == [] and Handler.seen == []


def test_second_address_is_used_when_first_fails(server):
    port = server.server_address[1]
    tried = []

    def connector(ip, _port, timeout):
        tried.append(ip)
        if ip == "93.184.216.34":
            raise ConnectionRefusedError
        return socket.create_connection(("127.0.0.1", port), timeout=timeout)

    client = SafeHttpClient(resolver=make_resolver("93.184.216.34", "93.184.216.35"), connector=connector)
    assert client.request("GET", "http://valid.example/ok").status == 200
    assert tried == ["93.184.216.34", "93.184.216.35"]


# ---------------------------------------------------------------- redirects


def test_relative_redirect_is_followed(server):
    r = make_client(server).request("GET", "http://valid.example/redir", max_body=10)
    assert r.status == 200 and r.body == b"hello"


@pytest.mark.parametrize("path", ["/to-internal", "/to-metadata", "/to-file"])
def test_redirects_to_internal_or_non_http_targets_are_refused(server, path):
    with pytest.raises(UrlValidationError):
        make_client(server).request("GET", f"http://valid.example{path}")
    assert [s["path"] for s in Handler.seen] == [path]  # the hostile hop was never contacted


def test_redirect_loop_is_cut_off(server):
    with pytest.raises(AppError) as exc:
        make_client(server, max_redirects=3).request("GET", "http://valid.example/loop")
    assert exc.value.reason == "redirect_limit" and len(Handler.seen) == 4


# ------------------------------------------------------------------ failures


def test_connection_refused_is_reported_as_source_unavailable():
    def refuse(ip, port, timeout):
        raise ConnectionRefusedError

    client = SafeHttpClient(resolver=make_resolver(PUBLIC_IP), connector=refuse)
    with pytest.raises(AppError) as exc:
        client.request("GET", "http://valid.example/")
    assert exc.value.code is ErrorCode.SOURCE_UNAVAILABLE


def test_timeout_is_reported_as_timeout():
    def slow(ip, port, timeout):
        raise TimeoutError

    client = SafeHttpClient(resolver=make_resolver(PUBLIC_IP), connector=slow)
    with pytest.raises(AppError) as exc:
        client.request("GET", "http://valid.example/")
    assert exc.value.code is ErrorCode.TIMEOUT


# ----------------------------------------------------------------------- TLS


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "k.pem"),
             "-out", str(d / "c.pem"), "-days", "2", "-subj", "/CN=valid.example",
             "-addext", "subjectAltName=DNS:valid.example"],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("openssl not available")
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(d / "c.pem", d / "k.pem")
    client_ctx = ssl.create_default_context(cafile=str(d / "c.pem"))
    return server_ctx, client_ctx


@pytest.fixture
def tls_server(tls_material, routes):
    routes = {**routes, "/downgrade": (302, {"Location": "http://valid.example/ok"}, b"")}
    s = _serve(routes, tls_material[0])
    yield s
    s.shutdown()


def tls_client(server, ctx, calls=None):
    port = server.server_address[1]

    def connector(ip, _port, timeout):
        if calls is not None:
            calls.append(ip)
        return socket.create_connection(("127.0.0.1", port), timeout=timeout)

    return SafeHttpClient(resolver=make_resolver(PUBLIC_IP), connector=connector, ssl_context=ctx)


def test_https_connects_to_pinned_ip_and_verifies_certificate_for_hostname(tls_server, tls_material):
    calls = []
    r = tls_client(tls_server, tls_material[1], calls).request("GET", "https://valid.example/ok", max_body=10)
    assert r.status == 200 and r.body == b"hello"
    assert calls == [PUBLIC_IP]


def test_https_rejects_certificate_for_a_different_hostname(tls_server, tls_material):
    with pytest.raises(AppError) as exc:
        tls_client(tls_server, tls_material[1]).request("GET", "https://other.example/ok")
    assert exc.value.code is ErrorCode.SOURCE_UNAVAILABLE


def test_https_rejects_untrusted_certificate(tls_server):
    with pytest.raises(AppError):
        tls_client(tls_server, ssl.create_default_context()).request("GET", "https://valid.example/ok")


def test_https_to_http_downgrade_is_refused(tls_server, tls_material):
    with pytest.raises(AppError) as exc:
        tls_client(tls_server, tls_material[1]).request("GET", "https://valid.example/downgrade")
    assert exc.value.reason == "https_downgrade"
