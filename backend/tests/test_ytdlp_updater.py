"""yt-dlp updater (no network: downloads are faked) and the new batch / retry / update API routes."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.services import ytdlp_updater as up
from backend.app.services.source_service import SourceService
from backend.app.services.ytdlp_updater import YtDlpUpdater, parse_sums, version_tuple

from .conftest import FakeSource, make_resolver
from .test_api_jobs import BASE, BlockingSource, URL, make_client, opened, settings, start, wait_status  # noqa: F401

ORIGINAL_ASSET_NAME = up.asset_name  # captured before the autouse fixture patches it
ASSET = "yt-dlp_linux"
BINARY = b"#!/bin/sh\necho 2026.11.01\n"
TAG = "2026.11.01"


def release_json(tag=TAG, binary_host="github.com"):
    return json.dumps({
        "tag_name": tag,
        "assets": [
            {"name": ASSET, "browser_download_url": f"https://{binary_host}/yt-dlp/yt-dlp/releases/download/{tag}/{ASSET}"},
            {"name": "SHA2-256SUMS", "browser_download_url": f"https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/SHA2-256SUMS"},
        ],
    }).encode()


class FakeNet:
    def __init__(self, binary=BINARY, sums_hash=None, tag=TAG, binary_host="github.com"):
        sums_hash = sums_hash or hashlib.sha256(binary).hexdigest()
        self.responses = {
            up.RELEASE_API: release_json(tag, binary_host),
            f"https://{binary_host}/yt-dlp/yt-dlp/releases/download/{tag}/{ASSET}": binary,
            f"https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/SHA2-256SUMS": f"{sums_hash}  {ASSET}\n".encode(),
        }
        self.calls = []

    def __call__(self, url, max_bytes):
        self.calls.append(url)
        return self.responses[url]


@pytest.fixture(autouse=True)
def linux_asset(monkeypatch):
    monkeypatch.setattr(up, "asset_name", lambda *a, **k: ASSET)
    monkeypatch.setattr(up, "binary_name", lambda: "yt-dlp")


def make_updater(tmp_path, net, current="2026.10.21", reported=TAG):
    return YtDlpUpdater(tmp_path / "bin", current_version=lambda: current, fetch=net, verify_runner=lambda p: reported)


# ------------------------------------------------------------ pure helpers


def test_parse_sums_and_versions():
    h = "a" * 64
    assert parse_sums(f"{h}  yt-dlp.exe\nnot a line\n{h} *yt-dlp_linux") == {"yt-dlp.exe": h, "yt-dlp_linux": h}
    assert version_tuple("2026.10.21") < version_tuple("2026.11.01") < version_tuple("2026.11.01.1")
    assert version_tuple("standalone") is None and version_tuple(None) is None


def test_asset_names_per_platform():
    assert ORIGINAL_ASSET_NAME("win32", "AMD64") == "yt-dlp.exe"
    assert ORIGINAL_ASSET_NAME("linux", "x86_64") == "yt-dlp_linux"
    assert ORIGINAL_ASSET_NAME("linux", "aarch64") == "yt-dlp_linux_aarch64"
    assert ORIGINAL_ASSET_NAME("darwin", "arm64") is None


# --------------------------------------------------------------- the update


def test_check_reports_available_update(tmp_path):
    info = make_updater(tmp_path, FakeNet()).check()
    assert info == {"current": "2026.10.21", "latest": TAG, "update_available": True, "supported": True}
    assert make_updater(tmp_path, FakeNet(), current=TAG).check()["update_available"] is False


def test_update_installs_verified_binary(tmp_path):
    updater = make_updater(tmp_path, FakeNet())
    result = updater.update()
    assert result == {"previous": "2026.10.21", "installed": TAG}
    assert updater.target.read_bytes() == BINARY
    assert not list((tmp_path / "bin").glob(".yt-dlp-*"))  # no temp leftovers


def test_checksum_mismatch_is_rejected_and_old_binary_kept(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "yt-dlp").write_bytes(b"old")
    updater = make_updater(tmp_path, FakeNet(sums_hash="0" * 64))
    with pytest.raises(AppError) as exc:
        updater.update()
    assert exc.value.reason == "checksum_mismatch"
    assert updater.target.read_bytes() == b"old"
    assert not list((tmp_path / "bin").glob(".yt-dlp-*"))


def test_binary_that_does_not_report_the_release_version_is_rejected(tmp_path):
    updater = make_updater(tmp_path, FakeNet(), reported="9999.01.01")
    with pytest.raises(AppError) as exc:
        updater.update()
    assert exc.value.reason == "verify_failed"
    assert not updater.target.exists()


def test_assets_on_foreign_hosts_are_refused(tmp_path):
    net = FakeNet(binary_host="evil.example")
    with pytest.raises(AppError) as exc:
        make_updater(tmp_path, net).update()
    assert exc.value.reason == "host_not_allowed"
    assert not any("evil.example" in c for c in net.calls)  # nothing was fetched from it


def test_redirects_to_other_hosts_are_blocked():
    handler = up._CheckedRedirects()
    with pytest.raises(Exception):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x")
    assert up._host_allowed("https://objects.githubusercontent.com/x")
    assert not up._host_allowed("http://github.com/x") and not up._host_allowed("https://github.com.evil.example/x")


def test_network_failure_gives_a_friendly_error(tmp_path):
    def boom(url, max_bytes):
        raise OSError("down")

    updater = YtDlpUpdater(tmp_path / "bin", current_version=lambda: None, fetch=boom)
    with pytest.raises(AppError) as exc:
        updater.check()
    assert "connection" in exc.value.message.lower()


# ------------------------------------------------------------------ routes


@pytest.fixture
def api(settings, opened, monkeypatch, tmp_path):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    stack = []

    def build(source=None, net=None):
        updater = make_updater(tmp_path, net or FakeNet())
        app = create_app(settings, source_service=SourceService([source or FakeSource()]), ytdlp_updater=updater)
        client = TestClient(app, base_url=BASE)
        client.__enter__()
        stack.append(client)
        client.headers.update({"X-Session-Token": app.state.session_token})
        return client

    yield build
    for c in stack:
        c.__exit__(None, None, None)


def test_update_routes(api):
    client = api()
    assert client.get("/api/system/extractor/update").json()["update_available"] is True
    assert client.post("/api/system/extractor/update").json()["installed"] == TAG


def test_update_is_refused_while_downloads_are_active(api):
    source = BlockingSource()
    client = api(source)
    assert start(client).status_code == 202
    assert source.started.wait(5)
    r = client.post("/api/system/extractor/update")
    assert r.status_code == 409
    source.release.set()


def test_batch_route_queues_best_quality_and_reports_failures(api):
    client = api()
    r = client.post("/api/jobs/batch", json={"urls": [URL, "https://media.example/gone", "nonsense"], "mode": "best"})
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] == 1 and body["failed"] == 2
    ok = next(i for i in body["items"] if i["ok"])
    wait_status(client, ok["job_id"], {"completed"})
    assert client.post("/api/jobs/batch", json={"urls": []}).status_code == 400
    assert client.post("/api/jobs/batch", json={"urls": ["https://media.example/x"] * 26}).status_code == 400


def test_retry_route(api):
    client = api(FakeSource())
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, {"completed"})
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409  # completed jobs are not retryable
    assert client.post("/api/jobs/not-a-job/retry").status_code == 404
