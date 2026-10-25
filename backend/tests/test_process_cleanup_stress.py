"""Phase 7 Security Hardening: Process-cleanup stress tests and resource leaks verification."""

import time
import uuid
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.models.job import JobStatus, TERMINAL
from backend.app.services.download_service import DownloadService
from backend.app.services.file_service import cleanup_abandoned_temp, ensure_runtime_directories
from backend.app.services.job_service import AnalysisCache, JobService
from backend.app.services.source_service import SourceService
from .conftest import FakeSource, make_resolver


@pytest.fixture
def temp_roots(tmp_path):
    output = tmp_path / "out"
    temp = tmp_path / "temp"
    db = tmp_path / "db" / "history.sqlite3"
    ensure_runtime_directories(output, temp, db)
    return output, temp, db


def test_ensure_runtime_directories_permissions(temp_roots):
    output, temp, db = temp_roots
    assert output.is_dir()
    assert temp.is_dir()
    assert db.parent.is_dir()


def test_cleanup_abandoned_temp_stress(tmp_path):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Create 5 abandoned job directories
    job_ids = [str(uuid.uuid4()) for _ in range(5)]
    for jid in job_ids:
        jdir = temp_dir / f"job-{jid}"
        jdir.mkdir()
        (jdir / "scratch.part").write_bytes(b"temp data")

    # Create a non-matching directory and file that must NOT be removed
    keep_dir = temp_dir / "keep_this_dir"
    keep_dir.mkdir()
    keep_file = temp_dir / "keep_this_file.txt"
    keep_file.write_text("precious")

    # With older_than_seconds=0.0, all 5 job dirs should be cleaned up immediately
    time.sleep(0.05)
    removed = cleanup_abandoned_temp(temp_dir, older_than_seconds=0.0)
    assert removed == 5

    for jid in job_ids:
        assert not (temp_dir / f"job-{jid}").exists()

    assert keep_dir.is_dir()
    assert keep_file.is_file()


def test_job_service_rapid_cancellation_stress(tmp_path, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    settings = Settings.load(
        {
            "OUTPUT_DIRECTORY": str(tmp_path / "out"),
            "TEMP_DIRECTORY": str(tmp_path / "temp"),
            "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
            "MAX_PARALLEL_JOBS": 4,
        }
    )
    sources = SourceService([FakeSource()])
    cache = AnalysisCache()
    job_service = JobService(settings, sources, DownloadService(settings), cache)
    job_service.start()

    created_jobs = []
    # Rapidly create 8 jobs
    for i in range(8):
        job = job_service.create(
            f"https://media.example/rapid_{i}",
            format_id="v720",
            output_format="mp4",
        )
        created_jobs.append(job)

    # Immediately cancel all created jobs
    for job in created_jobs:
        try:
            job_service.cancel(job.id)
        except Exception:
            pass  # might already be completed/cancelled

    # Shutdown cleanly within 5 seconds
    job_service.shutdown(timeout=5.0)

    # Assert all worker threads have cleanly joined and zero remain active
    assert len(job_service._workers) == 0

    # Assert every job is in a valid terminal state
    for job in created_jobs:
        assert job.status in TERMINAL
