import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.models.job import Job, JobStatus
from backend.app.services.history_service import HistoryService
from backend.app.services.source_service import SourceService
from .conftest import FakeSource

BASE = "http://127.0.0.1:8000"


@pytest.fixture
def history_db(tmp_path):
    return tmp_path / "test_history.sqlite3"


@pytest.fixture
def history_service(history_db):
    return HistoryService(history_db)


@pytest.fixture
def app(tmp_path, history_service):
    settings = Settings.load(
        {
            "OUTPUT_DIRECTORY": str(tmp_path / "out"),
            "TEMP_DIRECTORY": str(tmp_path / "temp"),
            "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
        }
    )
    return create_app(
        settings,
        source_service=SourceService([FakeSource()]),
        history_service=history_service,
    )


@pytest.fixture
def client(app):
    with TestClient(app, base_url=BASE) as c:
        yield c


@pytest.fixture
def auth(app):
    return {"X-Session-Token": app.state.session_token}


# ------------------------------------------------------------- service unit tests


def test_history_service_record_and_list(history_service, tmp_path):
    test_file = tmp_path / "sample.mp4"
    test_file.write_bytes(b"sample video bytes")

    job = Job(url="https://youtube.com/watch?v=abc12345", title="Test Video", format_id="best", output_format="mp4")
    job.transition(JobStatus.DOWNLOADING)
    job.transition(JobStatus.COMPLETED)
    job.output_path = test_file
    job.filename = "sample.mp4"
    job.file_size = len(b"sample video bytes")

    item = history_service.record(job, source="YouTube", format_label="MP4")
    assert item is not None
    assert item.title == "Test Video"
    assert item.file_exists is True

    items = history_service.list()
    assert len(items) == 1
    assert items[0].id == job.id
    assert items[0].filename == "sample.mp4"
    assert items[0].format_label == "MP4"


def test_history_service_get_and_delete(history_service, tmp_path):
    test_file = tmp_path / "audio.mp3"
    test_file.write_bytes(b"audio")

    job = Job(url="https://youtube.com/watch?v=audio123", title="Song", format_id="audio", output_format="mp3")
    job.transition(JobStatus.DOWNLOADING)
    job.transition(JobStatus.COMPLETED)
    job.output_path = test_file
    job.filename = "audio.mp3"

    history_service.record(job, source="YouTube", format_label="MP3")

    fetched = history_service.get(job.id)
    assert fetched is not None
    assert fetched.title == "Song"

    assert history_service.delete(job.id) is True
    assert history_service.get(job.id) is None
    assert history_service.delete("non-existent") is False


def test_history_completed_file_validation(history_service, tmp_path):
    safe_file = tmp_path / "video.mp4"
    safe_file.write_bytes(b"video")

    job = Job(url="https://youtube.com/watch?v=safe123", title="Safe", format_id="best", output_format="mp4")
    job.transition(JobStatus.DOWNLOADING)
    job.transition(JobStatus.COMPLETED)
    job.output_path = safe_file
    job.filename = "video.mp4"

    history_service.record(job)
    resolved = history_service.completed_file(job.id)
    assert resolved == safe_file.resolve()

    # If file was deleted from disk
    safe_file.unlink()
    with pytest.raises(AppError) as exc_info:
        history_service.completed_file(job.id)
    assert exc_info.value.status_code == 404


# ----------------------------------------------------------------- API routes


def test_history_api_list_empty(client, auth):
    res = client.get("/api/history", headers=auth)
    assert res.status_code == 200
    assert res.json() == {"items": []}


def test_history_api_flow(client, auth, history_service, tmp_path):
    media_file = tmp_path / "clip.mkv"
    media_file.write_bytes(b"clip content")

    job = Job(url="https://youtube.com/watch?v=clip1", title="My Clip", format_id="mkv-best", output_format="mkv")
    job.transition(JobStatus.DOWNLOADING)
    job.transition(JobStatus.COMPLETED)
    job.output_path = media_file
    job.filename = "clip.mkv"

    history_service.record(job, source="YouTube", format_label="MKV")

    # List
    res = client.get("/api/history", headers=auth)
    assert res.status_code == 200
    data = res.json()["items"]
    assert len(data) == 1
    assert data[0]["title"] == "My Clip"
    assert data[0]["file_exists"] is True

    # Get single
    res_single = client.get(f"/api/history/{job.id}", headers=auth)
    assert res_single.status_code == 200
    assert res_single.json()["filename"] == "clip.mkv"

    # Delete
    res_del = client.delete(f"/api/history/{job.id}", headers=auth)
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # Get 404 after delete
    res_after = client.get(f"/api/history/{job.id}", headers=auth)
    assert res_after.status_code == 404


def test_history_api_open(client, auth, history_service, tmp_path, app):
    media_file = tmp_path / "song.mp3"
    media_file.write_bytes(b"mp3 content")

    job = Job(url="https://youtube.com/watch?v=song1", title="Song", format_id="mp3", output_format="mp3")
    job.transition(JobStatus.DOWNLOADING)
    job.transition(JobStatus.COMPLETED)
    job.output_path = media_file
    job.filename = "song.mp3"

    history_service.record(job, source="YouTube", format_label="MP3")

    calls = []
    app.state.opener = lambda path, select=False: calls.append((path, select))

    # Open file
    res = client.post(f"/api/history/{job.id}/open", json={"action": "file"}, headers=auth)
    assert res.status_code == 200
    assert calls[-1] == (media_file.resolve(), False)

    # Open folder
    res_folder = client.post(f"/api/history/{job.id}/open", json={"action": "folder"}, headers=auth)
    assert res_folder.status_code == 200
    assert calls[-1] == (media_file.resolve(), True)
