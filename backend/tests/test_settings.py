import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services.settings_service import SettingsService
from backend.app.services.source_service import SourceService
from .conftest import FakeSource

BASE = "http://127.0.0.1:8000"


@pytest.fixture
def settings_db(tmp_path):
    return tmp_path / "test_settings.sqlite3"


@pytest.fixture
def settings_instance(tmp_path, settings_db):
    return Settings.load(
        {
            "OUTPUT_DIRECTORY": str(tmp_path / "default_out"),
            "TEMP_DIRECTORY": str(tmp_path / "temp"),
            "DATABASE_PATH": str(settings_db),
        }
    )


@pytest.fixture
def settings_service(settings_db, settings_instance):
    return SettingsService(settings_db, settings_instance)


@pytest.fixture
def app(tmp_path, settings_instance, settings_service):
    return create_app(
        settings_instance,
        source_service=SourceService([FakeSource()]),
        settings_service=settings_service,
    )


@pytest.fixture
def client(app):
    with TestClient(app, base_url=BASE) as c:
        yield c


@pytest.fixture
def auth(app):
    return {"X-Session-Token": app.state.session_token}


# ------------------------------------------------------------- service unit tests


def test_settings_service_default(settings_service, tmp_path):
    assert settings_service.get_output_directory() == (tmp_path / "default_out").resolve()
    all_settings = settings_service.get_all()
    assert "output_directory" in all_settings
    assert "allowed_source_domains" in all_settings


def test_settings_service_update_and_reload(tmp_path, settings_db, settings_instance):
    svc = SettingsService(settings_db, settings_instance)
    new_dir = tmp_path / "custom_out"
    svc.update_output_directory(str(new_dir))
    assert svc.get_output_directory() == new_dir.resolve()
    assert new_dir.is_dir()

    # Recreate service with same DB to check persistence
    new_settings_obj = Settings.load(
        {
            "OUTPUT_DIRECTORY": str(tmp_path / "original_out"),
            "TEMP_DIRECTORY": str(tmp_path / "temp"),
            "DATABASE_PATH": str(settings_db),
        }
    )
    svc2 = SettingsService(settings_db, new_settings_obj)
    assert svc2.get_output_directory() == new_dir.resolve()


def test_settings_service_rejects_empty_or_unsafe(settings_service):
    with pytest.raises(Exception):
        settings_service.update_output_directory("")
    with pytest.raises(Exception):
        settings_service.update_output_directory("relative/path/not/allowed")


# ----------------------------------------------------------------- API routes


def test_settings_api_get(client, auth, tmp_path):
    res = client.get("/api/settings", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert data["output_directory"] == str((tmp_path / "default_out").resolve())
    assert isinstance(data["allowed_source_domains"], list)
    assert data["max_parallel_jobs"] > 0


def test_settings_api_update_success(client, auth, tmp_path):
    new_target = tmp_path / "new_download_folder"
    res = client.put(
        "/api/settings",
        json={"output_directory": str(new_target)},
        headers=auth,
    )
    assert res.status_code == 200
    assert res.json()["output_directory"] == str(new_target.resolve())
    assert new_target.is_dir()


def test_settings_api_update_invalid(client, auth):
    res = client.put(
        "/api/settings",
        json={"output_directory": "relative/path"},
        headers=auth,
    )
    assert res.status_code == 400
    assert "The output directory must be an absolute path." in res.text


def test_settings_api_update_domains(client, auth):
    res = client.put(
        "/api/settings",
        json={"allowed_source_domains": ["archive.org", "youtube.com", "vimeo.com"]},
        headers=auth,
    )
    assert res.status_code == 200
    domains = res.json()["allowed_source_domains"]
    assert "youtube.com" in domains
    assert "vimeo.com" in domains

    # Reject invalid domain syntax
    res_bad = client.put(
        "/api/settings",
        json={"allowed_source_domains": ["bad domain with spaces"]},
        headers=auth,
    )
    assert res_bad.status_code == 400


def test_settings_api_universal_mode(client, auth):
    res = client.put(
        "/api/settings",
        json={"universal_mode": True},
        headers=auth,
    )
    assert res.status_code == 200
    assert res.json()["universal_mode"] is True
    assert "*" in res.json()["allowed_source_domains"]

    res_off = client.put(
        "/api/settings",
        json={"universal_mode": False},
        headers=auth,
    )
    assert res_off.status_code == 200
    assert res_off.json()["universal_mode"] is False
    assert "instagram.com" in res_off.json()["allowed_source_domains"]
    assert "facebook.com" in res_off.json()["allowed_source_domains"]


def test_settings_api_cookies_lifecycle(client, auth):
    # Initial status
    status = client.get("/api/settings/cookies", headers=auth)
    assert status.status_code == 200
    assert status.json()["has_cookies"] is False

    # Upload cookies
    cookie_sample = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t1799999999\tsessionid\t123456\n"
        ".facebook.com\tTRUE\t/\tTRUE\t1799999999\tc_user\t987654\n"
    )
    saved = client.post("/api/settings/cookies", json={"cookies_content": cookie_sample}, headers=auth)
    assert saved.status_code == 200
    data = saved.json()
    assert data["has_cookies"] is True
    assert "instagram.com" in data["domains_authenticated"]
    assert "facebook.com" in data["domains_authenticated"]

    # Delete cookies
    deleted = client.delete("/api/settings/cookies", headers=auth)
    assert deleted.status_code == 200
    assert deleted.json()["has_cookies"] is False

