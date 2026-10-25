import errno
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.app.core.errors import AppError, ErrorCode, OperationCancelled
from backend.app.services import http_client
from backend.app.services.http_client import SafeHttpClient
from backend.app.utils.urls import UrlValidationError

from .conftest import make_resolver

PAYLOAD = bytes(range(256)) * 1200  # 307,200 bytes


class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        try:
            self._serve()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve(self):
        path = self.path
        if path == "/file":
            self.send_response(200); self.send_header("Content-Length", str(len(PAYLOAD))); self.end_headers()
            self.wfile.write(PAYLOAD)
        elif path == "/short":  # promises more than it sends, then hangs up
            self.send_response(200); self.send_header("Content-Length", "100000"); self.end_headers()
            self.wfile.write(b"x" * 40000); self.wfile.flush(); self.close_connection = True
        elif path == "/liar":  # no Content-Length, keeps sending
            self.send_response(200); self.end_headers()
            for _ in range(100):
                self.wfile.write(b"y" * 10000)
        elif path == "/huge":
            self.send_response(200); self.send_header("Content-Length", str(10**12)); self.end_headers()
        elif path == "/slow":
            self.send_response(200); self.send_header("Content-Length", "1000000"); self.end_headers()
            for _ in range(100):
                self.wfile.write(b"z" * 10000); self.wfile.flush(); time.sleep(0.05)
        elif path == "/stall":
            self.send_response(200); self.send_header("Content-Length", "1000"); self.end_headers()
            self.wfile.write(b"a" * 10); self.wfile.flush(); time.sleep(2)
        elif path == "/internal":
            self.send_response(302); self.send_header("Location", "http://127.0.0.1/secret"); self.end_headers()
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()


@pytest.fixture(scope="module")
def server():
    s = ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield s
    s.shutdown()


def client(server, **kw):
    port = server.server_address[1]
    return SafeHttpClient(
        resolver=make_resolver("93.184.216.34"),
        connector=lambda ip, p, t: socket.create_connection(("127.0.0.1", port), timeout=t),
        **kw,
    )


URL = "http://valid.example"
BIG = 10**9


def test_download_writes_exact_bytes_and_reports_progress(server, tmp_path):
    updates = []
    dest = tmp_path / "f.bin"
    n = client(server).download_file(f"{URL}/file", dest, max_bytes=BIG, on_progress=updates.append)
    assert n == len(PAYLOAD) and dest.read_bytes() == PAYLOAD
    assert updates and updates[-1].downloaded == len(PAYLOAD) and updates[-1].total == len(PAYLOAD)
    assert [u.downloaded for u in updates] == sorted(u.downloaded for u in updates)


def test_cancel_mid_stream_stops_quickly(server, tmp_path):
    cancel = threading.Event()
    started = time.time()

    def on_progress(p):
        if p.downloaded > 20000:
            cancel.set()

    with pytest.raises(OperationCancelled):
        client(server).download_file(f"{URL}/slow", tmp_path / "f.bin", max_bytes=BIG, cancel=cancel, on_progress=on_progress)
    assert time.time() - started < 3  # the full transfer would take ~5 s


def test_truncated_body_is_a_lost_connection_not_success(server, tmp_path):
    with pytest.raises(AppError) as exc:
        client(server).download_file(f"{URL}/short", tmp_path / "f.bin", max_bytes=BIG)
    assert exc.value.reason == "connection_lost" and exc.value.code is ErrorCode.SOURCE_UNAVAILABLE


def test_server_that_lies_about_length_is_cut_off_at_the_limit(server, tmp_path):
    dest = tmp_path / "f.bin"
    with pytest.raises(AppError) as exc:
        client(server).download_file(f"{URL}/liar", dest, max_bytes=50_000)
    assert exc.value.reason == "too_large" and dest.stat().st_size <= 50_000


def test_declared_oversize_is_refused_before_writing_anything(server, tmp_path):
    dest = tmp_path / "f.bin"
    with pytest.raises(AppError) as exc:
        client(server).download_file(f"{URL}/huge", dest, max_bytes=BIG)
    assert exc.value.reason == "too_large" and not dest.exists()


def test_http_errors_are_categorized(server, tmp_path):
    with pytest.raises(AppError) as exc:
        client(server).download_file(f"{URL}/missing", tmp_path / "f.bin", max_bytes=BIG)
    assert exc.value.code is ErrorCode.MEDIA_NOT_AVAILABLE


def test_redirect_to_internal_address_is_refused(server, tmp_path):
    with pytest.raises(UrlValidationError):
        client(server).download_file(f"{URL}/internal", tmp_path / "f.bin", max_bytes=BIG)


def test_stalled_server_times_out(server, tmp_path):
    with pytest.raises(AppError) as exc:
        client(server, timeout=0.4).download_file(f"{URL}/stall", tmp_path / "f.bin", max_bytes=BIG)
    assert exc.value.code is ErrorCode.TIMEOUT and exc.value.reason == "read_timeout"


def test_existing_destination_is_never_overwritten(server, tmp_path):
    dest = tmp_path / "f.bin"
    dest.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        client(server).download_file(f"{URL}/file", dest, max_bytes=BIG)
    assert dest.read_bytes() == b"precious"


def test_disk_full_is_reported_as_such(server, tmp_path, monkeypatch):
    class FullDisk:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def write(self, data): raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(http_client, "open", lambda *a, **k: FullDisk(), raising=False)
    with pytest.raises(AppError) as exc:
        client(server).download_file(f"{URL}/file", tmp_path / "f.bin", max_bytes=BIG)
    assert exc.value.code is ErrorCode.DISK_SPACE_LOW
