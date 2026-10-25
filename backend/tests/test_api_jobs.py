import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.errors import OperationCancelled
from backend.app.main import create_app
from backend.app.services.source_service import SourceService

from .conftest import FakeSource, make_resolver

BASE = "http://127.0.0.1:8000"
URL = "https://media.example/v"
PUBLIC = "93.184.216.34"


class BlockingSource(FakeSource):
    """Like FakeSource, but the download waits until released or cancelled."""

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def download(self, url, fmt, dest_dir, part, ctx):
        self.started.set()
        while not self.release.is_set():
            if ctx.cancel.wait(0.02):
                raise OperationCancelled
        return super().download(url, fmt, dest_dir, part, ctx)


@pytest.fixture
def settings(tmp_path):
    return Settings.load({
        "OUTPUT_DIRECTORY": str(tmp_path / "out"),
        "TEMP_DIRECTORY": str(tmp_path / "temp"),
        "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
    })


@pytest.fixture
def opened():
    return []


@pytest.fixture
def make_client(settings, opened, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver(PUBLIC))
    stack = []

    def build(source=None):
        app = create_app(
            settings,
            source_service=SourceService([source or FakeSource()]),
            opener=lambda path, select=False: opened.append((path, select)),
        )
        client = TestClient(app, base_url=BASE)
        client.__enter__()
        stack.append(client)
        client.headers.update({"X-Session-Token": app.state.session_token})
        return client

    yield build
    for c in stack:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def start(client, fmt="v720", output=None, url=URL):
    body = {"url": url, "format_id": fmt}
    if output:
        body["output_format"] = output
    return client.post("/api/jobs", json=body)


def wait_status(client, job_id, wanted, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in wanted:
            return data
        time.sleep(0.03)
    raise AssertionError(f"job stuck: {data}")


# ------------------------------------------------------------ happy path


def test_full_flow_analyze_download_complete(client, settings, tmp_path):
    assert client.post("/api/media/analyze", json={"url": URL}).status_code == 200
    r = start(client)
    assert r.status_code == 202
    body = r.json()
    assert set(body) == {"job_id", "status"} and body["status"] in ("queued", "downloading")

    done = wait_status(client, body["job_id"], {"completed", "failed"})
    assert done["status"] == "completed" and done["progress"] == 100
    assert done["filename"].endswith(".mp4") and done["file_size"] == 100_000
    assert done["error"] is None and done["started_at"] and done["completed_at"]
    assert (settings.output_directory / done["filename"]).stat().st_size == 100_000
    assert list(settings.temp_directory.iterdir()) == []


def test_responses_never_contain_filesystem_paths(client, tmp_path):
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, {"completed"})
    for path in (f"/api/jobs/{job_id}", "/api/jobs"):
        text = client.get(path).text
        assert str(tmp_path) not in text and "/out/" not in text and "temp" not in text.lower().replace("template", "")


def test_hostile_title_results_in_a_safe_file_in_the_output_folder(make_client, settings):
    class Hostile(FakeSource):
        def analyze(self, url):
            info = super().analyze(url)
            import dataclasses

            return dataclasses.replace(info, title="..\\..\\..\\Windows\\System32\\evil:*?.exe")

    c = make_client(Hostile())
    job_id = start(c).json()["job_id"]
    done = wait_status(c, job_id, {"completed"})
    assert "/" not in done["filename"] and "\\" not in done["filename"] and ":" not in done["filename"]
    assert done["filename"].endswith(".mp4")
    assert [p.name for p in settings.output_directory.iterdir()] == [done["filename"]]


def test_job_list_is_newest_first(client):
    ids = [start(client).json()["job_id"] for _ in range(3)]
    wait_status(client, ids[-1], {"completed"})
    listed = [j["job_id"] for j in client.get("/api/jobs").json()["jobs"]]
    assert listed == ids[::-1]


def test_audio_format_downloads_with_its_own_container(client):
    job_id = start(client, fmt="a128").json()["job_id"]
    assert wait_status(client, job_id, {"completed"})["filename"].endswith(".m4a")


# ------------------------------------------------------------ open file/folder


def test_open_file_and_folder_use_the_servers_own_path(client, opened, settings):
    job_id = start(client).json()["job_id"]
    done = wait_status(client, job_id, {"completed"})
    assert client.post(f"/api/jobs/{job_id}/open", json={"action": "file"}).json() == {"opened": True}
    assert client.post(f"/api/jobs/{job_id}/open", json={"action": "folder"}).status_code == 200
    expected = settings.output_directory.resolve() / done["filename"]
    assert opened == [(expected, False), (expected, True)]


@pytest.mark.parametrize("body", [{"action": "exec"}, {"action": "file", "path": "/etc/passwd"}, {}, {"action": ["file"]}])
def test_open_rejects_anything_but_file_or_folder(client, body, opened):
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, {"completed"})
    r = client.post(f"/api/jobs/{job_id}/open", json=body)
    assert r.status_code == 400 and opened == []


def test_open_refuses_files_outside_the_output_folder_or_missing(client, opened, tmp_path):
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, {"completed"})
    job = client.app.state.job_service.get(job_id)
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"x")
    original = job.output_path
    job.output_path = secret  # simulate a tampered record
    assert client.post(f"/api/jobs/{job_id}/open", json={"action": "file"}).status_code == 404
    job.output_path = original.with_suffix(".exe")
    original.rename(job.output_path)
    assert client.post(f"/api/jobs/{job_id}/open", json={"action": "file"}).status_code == 404
    assert opened == []


def test_open_unknown_or_unfinished_job_is_not_found(make_client, opened):
    src = BlockingSource()
    c = make_client(src)
    job_id = start(c).json()["job_id"]
    assert src.started.wait(5)
    assert c.post(f"/api/jobs/{job_id}/open", json={"action": "file"}).status_code == 404
    assert c.post("/api/jobs/00000000-0000-4000-8000-000000000000/open", json={"action": "file"}).status_code == 404
    assert opened == []
    src.release.set()


# ------------------------------------------------------------ cancel


def test_cancel_running_job_via_api(make_client, settings):
    src = BlockingSource()
    c = make_client(src)
    job_id = start(c).json()["job_id"]
    assert src.started.wait(5)
    r = c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200
    done = wait_status(c, job_id, {"cancelled"})
    assert done["stage"] == "Cancelled" and done["filename"] is None
    deadline = time.time() + 3
    while list(settings.temp_directory.iterdir()) and time.time() < deadline:
        time.sleep(0.02)
    assert list(settings.temp_directory.iterdir()) == []
    assert not settings.output_directory.exists() or list(settings.output_directory.iterdir()) == []


def test_cancel_finished_job_is_409(client):
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, {"completed"})
    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_REQUEST"


# ------------------------------------------------------------ validation & guards


def test_jobs_api_needs_the_session_token_and_a_local_origin(client):
    body = {"url": URL, "format_id": "v720"}
    assert client.post("/api/jobs", json=body, headers={"X-Session-Token": "wrong"}).status_code == 403
    assert client.get("/api/jobs", headers={"X-Session-Token": ""}).status_code == 403
    assert client.post("/api/jobs", json=body, headers={"Origin": "http://evil.example"}).status_code == 403


@pytest.mark.parametrize(
    "body",
    [{}, {"url": URL}, {"format_id": "v720"}, {"url": URL, "format_id": ""}, {"url": URL, "format_id": 5},
     {"url": URL, "format_id": "v720", "extra": 1}, {"url": URL, "format_id": "x" * 101},
     {"url": URL, "format_id": "v720", "output_format": "x" * 11}, []],
)
def test_malformed_job_requests_are_rejected(client, body):
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "fmt,output,code",
    [("nope", None, "FORMAT_NOT_AVAILABLE"), ("v720; rm -rf /", None, "FORMAT_NOT_AVAILABLE"),
     ("--exec=calc", None, "FORMAT_NOT_AVAILABLE"), ("v720", "exe", "FORMAT_NOT_AVAILABLE"),
     ("v720", "mp3", "FORMAT_NOT_AVAILABLE"), ("a128", "mp4", "FORMAT_NOT_AVAILABLE")],
)
def test_unknown_formats_and_impossible_outputs_are_refused_up_front(client, fmt, output, code):
    r = start(client, fmt=fmt, output=output)
    assert r.status_code == 400 and r.json()["error"]["code"] == code
    assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "file:///etc/passwd", "http://169.254.169.254/", "https://other.example/x"])
def test_dangerous_or_unsupported_urls_never_become_jobs(client, url):
    r = start(client, url=url)
    assert r.status_code == 400 and r.json()["error"]["code"] in ("INVALID_URL", "UNSUPPORTED_SOURCE")
    assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("job_id", ["nope", "..%2f..%2fetc%2fpasswd", "00000000-0000-4000-8000-000000000000", "%00", "A" * 500])
def test_bad_job_ids_are_plain_404s(client, job_id):
    for r in (client.get(f"/api/jobs/{job_id}"), client.post(f"/api/jobs/{job_id}/cancel")):
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND" and "Traceback" not in r.text


def test_jobs_work_even_if_the_page_never_called_analyze_first(client):
    # The cache is only an optimisation; the server re-analyzes when needed.
    job_id = start(client).json()["job_id"]
    assert wait_status(client, job_id, {"completed"})["status"] == "completed"


def test_server_shutdown_cancels_running_downloads(make_client, settings):
    src = BlockingSource()
    c = make_client(src)
    job_id = start(c).json()["job_id"]
    assert src.started.wait(5)
    job = c.app.state.job_service.get(job_id)
    c.__exit__(None, None, None)  # lifespan shutdown
    assert job.status.value == "cancelled"
    assert list(settings.temp_directory.iterdir()) == []


def test_a_real_job_id_only_works_in_its_one_canonical_spelling(client):
    job_id = start(client).json()["job_id"]
    wait_status(client, job_id, {"completed"})
    import uuid

    variants = [job_id.upper(), "{" + job_id + "}", "urn:uuid:" + job_id, job_id.replace("-", ""), " " + job_id]
    assert client.get(f"/api/jobs/{job_id}").status_code == 200
    for v in variants:
        assert client.get(f"/api/jobs/{v}").status_code == 404, v
        assert client.post(f"/api/jobs/{v}/cancel").status_code == 404, v


def test_the_queue_has_a_hard_limit(make_client, monkeypatch):
    from backend.app.services import job_service

    monkeypatch.setattr(job_service, "MAX_ACTIVE_JOBS", 2)
    src = BlockingSource()
    c = make_client(src)
    assert start(c).status_code == 202 and start(c).status_code == 202
    r = start(c)
    assert r.status_code == 429 and r.json()["error"]["code"] == "INVALID_REQUEST"
    src.release.set()
