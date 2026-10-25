"""Phase 7 Security Hardening: Malformed-input sweep across all API endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services.source_service import SourceService
from .conftest import FakeSource

BASE = "http://127.0.0.1:8000"

SQL_INJECTION_STRINGS = [
    "' OR '1'='1",
    "'; DROP TABLE downloads;--",
    "1' UNION SELECT 1,2,3,4,5,6,7,8,9--",
    "' OR 1=1--",
    "admin' --",
    "' WAITFOR DELAY '0:0:5'--",
]

PATH_TRAVERSAL_STRINGS = [
    "../../../../../../etc/passwd",
    "..\\..\\..\\..\\Windows\\System32\\cmd.exe",
    "....//....//....//etc/shadow",
    "/etc/passwd\x00.mp4",
    "C:\\Windows\\System32\\drivers\\etc\\hosts",
    "\\\\.\\C:\\boot.ini",
]

MALFORMED_SCHEMES = [
    "file:///etc/passwd",
    "file:///C:/Windows/System32/calc.exe",
    "ftp://example.com/file.mp4",
    "gopher://gopher.example.com",
    "javascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "ssh://user@example.com",
]


@pytest.fixture
def app(tmp_path):
    settings = Settings.load(
        {
            "OUTPUT_DIRECTORY": str(tmp_path / "out"),
            "TEMP_DIRECTORY": str(tmp_path / "temp"),
            "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
        }
    )
    return create_app(settings, source_service=SourceService([FakeSource()]))


@pytest.fixture
def client(app):
    with TestClient(app, base_url=BASE) as c:
        yield c


@pytest.fixture
def auth(app):
    return {"X-Session-Token": app.state.session_token}


# ------------------------------------------------------------- URL & Scheme Sweep


@pytest.mark.parametrize("scheme_url", MALFORMED_SCHEMES)
def test_analyze_rejects_malformed_schemes(client, auth, scheme_url):
    res = client.post("/api/media/analyze", json={"url": scheme_url}, headers=auth)
    assert res.status_code in (400, 422)


@pytest.mark.parametrize("scheme_url", MALFORMED_SCHEMES)
def test_job_create_rejects_malformed_schemes(client, auth, scheme_url):
    res = client.post(
        "/api/jobs",
        json={"url": scheme_url, "format_id": "best", "output_format": "mp4"},
        headers=auth,
    )
    assert res.status_code in (400, 422)


def test_oversized_url_rejected(client, auth):
    giant_url = "https://youtube.com/watch?v=" + ("a" * 8192)
    res = client.post("/api/media/analyze", json={"url": giant_url}, headers=auth)
    assert res.status_code in (400, 414, 422)


def test_null_byte_in_url_rejected(client, auth):
    res = client.post("/api/media/analyze", json={"url": "https://youtube.com/watch?v=123\x00456"}, headers=auth)
    assert res.status_code in (400, 422)


# ------------------------------------------------------------- SQL Injection Sweep


@pytest.mark.parametrize("sqli", SQL_INJECTION_STRINGS)
def test_history_endpoints_sql_injection_safe(client, auth, sqli):
    # GET /api/history/{id}
    res_get = client.get(f"/api/history/{sqli}", headers=auth)
    assert res_get.status_code in (400, 404)

    # DELETE /api/history/{id}
    res_del = client.delete(f"/api/history/{sqli}", headers=auth)
    assert res_del.status_code in (400, 404)

    # POST /api/history/{id}/open
    res_open = client.post(f"/api/history/{sqli}/open", json={"action": "file"}, headers=auth)
    assert res_open.status_code in (400, 404)


@pytest.mark.parametrize("sqli", SQL_INJECTION_STRINGS)
def test_job_endpoints_sql_injection_safe(client, auth, sqli):
    # GET /api/jobs/{id}
    res_get = client.get(f"/api/jobs/{sqli}", headers=auth)
    assert res_get.status_code in (400, 404)

    # POST /api/jobs/{id}/cancel
    res_cancel = client.post(f"/api/jobs/{sqli}/cancel", headers=auth)
    assert res_cancel.status_code in (400, 404)


# --------------------------------------------------------- Path Traversal Sweep


@pytest.mark.parametrize("traversal", PATH_TRAVERSAL_STRINGS)
def test_settings_rejects_path_traversal(client, auth, traversal):
    res = client.put("/api/settings", json={"output_directory": traversal}, headers=auth)
    assert res.status_code in (400, 422)


@pytest.mark.parametrize("traversal", PATH_TRAVERSAL_STRINGS)
def test_job_create_rejects_traversal_format_and_output(client, auth, traversal):
    res = client.post(
        "/api/jobs",
        json={"url": "https://youtube.com/watch?v=abc12345", "format_id": traversal, "output_format": traversal},
        headers=auth,
    )
    assert res.status_code in (400, 422)


# --------------------------------------------------------- Malformed Payloads & Types


def test_malformed_json_body_handled(client, auth):
    res = client.post(
        "/api/media/analyze",
        content=b"not valid json {{{",
        headers={**auth, "Content-Type": "application/json"},
    )
    assert res.status_code in (400, 422)


def test_empty_json_object_rejected(client, auth):
    res = client.post("/api/media/analyze", json={}, headers=auth)
    assert res.status_code in (400, 422)


def test_unsupported_http_method(client, auth):
    res = client.patch("/api/jobs", json={}, headers=auth)
    assert res.status_code in (404, 405)


def test_missing_auth_header_rejected_with_401_or_403(client):
    res = client.get("/api/settings")
    assert res.status_code in (401, 403)
