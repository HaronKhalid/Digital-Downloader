import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import ConfigError, Settings
from backend.app.main import create_app

from .conftest import make_resolver

BASE = "http://127.0.0.1:8000"


@pytest.fixture
def app(tmp_path):
    settings = Settings.load(
        {
            "OUTPUT_DIRECTORY": str(tmp_path / "out"),
            "TEMP_DIRECTORY": str(tmp_path / "temp"),
            "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
        }
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, base_url=BASE) as c:
        yield c


@pytest.fixture
def auth(app):
    return {"X-Session-Token": app.state.session_token}


# --------------------------------------------------------------- config


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::", ""])
def test_non_loopback_host_refused(host):
    with pytest.raises(ConfigError):
        Settings.load({"HOST": host})


def test_defaults_bind_to_loopback():
    assert Settings.load({}).host == "127.0.0.1"


def test_wildcard_cors_refused():
    with pytest.raises(ConfigError):
        Settings.load({"CORS_ORIGINS": "*"})


def test_startup_creates_runtime_directories(app, tmp_path):
    with TestClient(app, base_url=BASE):
        pass
    assert (tmp_path / "out").is_dir() and (tmp_path / "temp").is_dir() and (tmp_path / "db").is_dir()


# ------------------------------------------------------ local-only guard


def test_health_is_open_and_minimal(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_api_requires_session_token(client, auth):
    assert client.get("/api/system/dependencies").status_code == 403
    assert client.get("/api/system/dependencies", headers={"X-Session-Token": "wrong"}).status_code == 403
    assert client.get("/api/system/dependencies", headers=auth).status_code == 200


def test_foreign_host_header_rejected_even_for_health(client):
    r = client.get("/api/health", headers={"Host": "evil.example"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PERMISSION_DENIED"


def test_dns_rebinding_host_with_wrong_port_rejected(client):
    assert client.get("/api/health", headers={"Host": "127.0.0.1:9999"}).status_code == 403


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "https://127.0.0.1:8000", "http://127.0.0.1:8001"])
def test_cross_origin_requests_rejected_even_with_token(client, auth, origin):
    r = client.post("/api/media/validate", json={"url": "https://valid.example/"}, headers={**auth, "Origin": origin})
    assert r.status_code == 403


def test_same_origin_request_allowed(client, auth, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    r = client.post("/api/media/validate", json={"url": "https://valid.example/"}, headers={**auth, "Origin": BASE})
    assert r.status_code == 200


def test_no_wildcard_cors_headers(client, auth):
    r = client.get("/api/system/dependencies", headers={**auth, "Origin": BASE})
    assert "access-control-allow-origin" not in r.headers


def test_index_serves_token_and_security_headers(client, app):
    r = client.get("/")
    assert r.status_code == 200
    assert app.state.session_token in r.text and "__SESSION_TOKEN__" not in r.text
    assert r.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_static_files_are_served_but_cannot_escape(client):
    assert client.get("/static/css/main.css").status_code == 200
    for probe in ("/static/%2e%2e/backend/app/main.py", "/static/..%2fbackend%2fapp%2fmain.py", "/static/../backend/app/main.py"):
        r = client.get(probe)
        assert "create_app" not in r.text


def test_api_docs_are_not_exposed(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# ------------------------------------------------------ validate endpoint


def test_validate_accepts_public_url(client, auth, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    r = client.post("/api/media/validate", json={"url": " HTTPS://Valid.Example/a?b=1#c "}, headers=auth)
    assert r.status_code == 200
    assert r.json() == {"valid": True, "normalized_url": "https://valid.example/a?b=1", "host": "valid.example"}


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "javascript:alert(1)", "http://127.0.0.1/", "http://localhost:8000/api/health",
     "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "https://user:pw@valid.example/"],
)
def test_validate_rejects_dangerous_urls_with_friendly_error(client, auth, url, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    r = client.post("/api/media/validate", json={"url": url}, headers=auth)
    assert r.status_code == 400
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == "INVALID_URL"
    assert body["error"]["message"] and "Traceback" not in r.text


def test_validate_rejects_host_resolving_to_internal_address(client, auth, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("127.0.0.1"))
    r = client.post("/api/media/validate", json={"url": "https://sneaky.example/"}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_URL"


@pytest.mark.parametrize("payload", [{}, {"url": ""}, {"url": 5}, {"url": "https://a.example/", "extra": 1}, []])
def test_validate_rejects_malformed_bodies(client, auth, payload):
    r = client.post("/api/media/validate", json=payload, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_route_returns_json_error_not_stack_trace(client, auth):
    r = client.get("/api/nope", headers=auth)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_dependencies_endpoint_shape(client, auth):
    data = client.get("/api/system/dependencies", headers=auth).json()
    assert data["backend"]["ok"] and data["python"]["ok"]
    assert set(data["ffmpeg"]) == {"ok", "version", "message"}


def test_missing_ffmpeg_gives_actionable_message(client, auth, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    ff = client.get("/api/system/dependencies", headers=auth).json()["ffmpeg"]
    assert ff["ok"] is False and "Install FFmpeg" in ff["message"]
