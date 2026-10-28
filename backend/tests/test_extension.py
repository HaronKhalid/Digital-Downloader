"""Browser-extension routes: pairing key, origin rules and queueing."""

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services.source_service import SourceService

from .conftest import FakeSource, make_resolver

BASE = "http://127.0.0.1:8000"
EXT_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
URL = "https://media.example/v"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    settings = Settings.load({
        "OUTPUT_DIRECTORY": str(tmp_path / "out"),
        "TEMP_DIRECTORY": str(tmp_path / "temp"),
        "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
    })
    return create_app(settings, source_service=SourceService([FakeSource()]), opener=lambda *a, **k: None)


@pytest.fixture
def client(app):
    with TestClient(app, base_url=BASE) as c:
        yield c


@pytest.fixture
def key(app):
    return app.state.extension_key.get()


def ext(key, origin=EXT_ORIGIN):
    return {"X-Extension-Key": key, "Origin": origin}


def test_ping_needs_the_key(client, key):
    assert client.get("/api/extension/ping").status_code == 403
    assert client.get("/api/extension/ping", headers=ext("wrong-key")).status_code == 403
    ok = client.get("/api/extension/ping", headers=ext(key))
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert ok.headers["access-control-allow-origin"] == EXT_ORIGIN


def test_firefox_origin_allowed_too(client, key):
    r = client.get("/api/extension/ping", headers=ext(key, "moz-extension://1234-abcd"))
    assert r.status_code == 200


def test_website_origin_rejected_even_with_key(client, key):
    r = client.get("/api/extension/ping", headers=ext(key, "https://evil.example"))
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_wrong_host_rejected(client, key):
    r = client.get("/api/extension/ping", headers={**ext(key), "Host": "evil.example"})
    assert r.status_code == 403


def test_preflight_only_for_extension_origins(client):
    good = client.options("/api/extension/send", headers={"Origin": EXT_ORIGIN, "Access-Control-Request-Method": "POST"})
    assert good.status_code == 204
    assert "x-extension-key" in good.headers["access-control-allow-headers"].lower()
    bad = client.options("/api/extension/send", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert bad.status_code == 403


def test_send_queues_links(client, key):
    r = client.post("/api/extension/send", json={"urls": [URL], "mode": "best"}, headers=ext(key))
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] == 1 and body["items"][0]["ok"] is True


def test_send_reports_bad_link_without_failing_the_rest(client, key):
    r = client.post("/api/extension/send", json={"urls": [URL, "https://other.example/x"], "mode": "audio"}, headers=ext(key))
    body = r.json()
    assert body["queued"] == 1 and body["failed"] == 1


def test_send_validates_input(client, key):
    assert client.post("/api/extension/send", json={"urls": []}, headers=ext(key)).status_code == 400
    assert client.post("/api/extension/send", json={"urls": [URL], "mode": "weird"}, headers=ext(key)).status_code == 400


def test_session_token_does_not_unlock_extension_routes(client, app):
    r = client.get("/api/extension/ping", headers={"X-Session-Token": app.state.session_token})
    assert r.status_code == 403


def test_pairing_routes_need_the_session_token_not_the_key(client, app, key):
    assert client.get("/api/extension/pairing", headers=ext(key)).status_code == 403
    r = client.get("/api/extension/pairing", headers={"X-Session-Token": app.state.session_token})
    assert r.status_code == 200
    assert r.json()["code"] == f"dd1.8000.{key}"


def test_rotating_disconnects_old_key(client, app, key):
    token = {"X-Session-Token": app.state.session_token}
    new = client.post("/api/extension/pairing/rotate", headers=token).json()["code"].split(".")[-1]
    assert new != key
    assert client.get("/api/extension/ping", headers=ext(key)).status_code == 403
    assert client.get("/api/extension/ping", headers=ext(new)).status_code == 200


def test_key_survives_restart(tmp_path):
    from backend.app.services.extension_key import ExtensionKey

    path = tmp_path / "k" / "key.txt"
    first = ExtensionKey(path).get()
    assert ExtensionKey(path).get() == first
    assert len(first) >= 32


def test_other_api_routes_still_reject_extension_origin(client, app):
    r = client.get("/api/jobs", headers={"X-Session-Token": app.state.session_token, "Origin": EXT_ORIGIN})
    assert r.status_code == 403
