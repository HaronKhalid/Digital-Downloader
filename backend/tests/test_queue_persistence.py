"""Persistent queue, restore-after-restart, retry and batch creation."""

import threading

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import AppError, ErrorCode
from backend.app.models.job import JobStatus
from backend.app.services.download_service import DownloadService
from backend.app.services.job_service import AnalysisCache, JobService
from backend.app.services.queue_store import QueueStore
from backend.app.services.source_service import SourceService
from core.formats.selector import pick_best

from .conftest import make_resolver
from .test_jobs import F, ScriptedSource, make_job, wait_for


@pytest.fixture
def settings(tmp_path):
    return Settings.load({
        "OUTPUT_DIRECTORY": str(tmp_path / "out"),
        "TEMP_DIRECTORY": str(tmp_path / "temp"),
        "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
    })


@pytest.fixture
def build(settings, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    settings.temp_directory.mkdir(parents=True, exist_ok=True)
    created = []

    def make(source):
        svc = JobService(
            settings,
            SourceService([source]),
            DownloadService(settings, retry_delays=(0.0, 0.0)),
            AnalysisCache(),
            store=QueueStore(settings.database_path),
        )
        svc.start()
        created.append(svc)
        return svc

    yield make
    for svc in created:
        svc.shutdown()


# ----------------------------------------------------------------- store


def test_store_tracks_active_and_finished_rows(settings):
    store = QueueStore(settings.database_path)
    job, _, _ = make_job(ScriptedSource())
    store.add(job)
    assert [s.id for s in store.pending()] == [job.id]
    job.fail("X", "boom")
    store.finish(job)
    assert store.pending() == []
    stored = store.get(job.id)
    assert stored.status == "failed" and stored.error_message == "boom"


# --------------------------------------------------------------- restore


def test_unfinished_downloads_are_restored_after_restart(build):
    block = threading.Event()
    first = build(ScriptedSource(block=block))
    running = first.create("https://media.example/v", "v1", None)
    queued = first.create("https://media.example/v", "v1", None)
    assert wait_for(lambda: running.status is JobStatus.DOWNLOADING)
    first.shutdown()  # app closes: both jobs are cancelled in memory but must stay restorable

    second = build(ScriptedSource())  # a "new run" over the same database
    assert wait_for(lambda: len(second.list()) == 2)
    assert wait_for(lambda: all(j.status is JobStatus.COMPLETED for j in second.list()))
    assert queued.id not in {j.id for j in second.list()}  # restored jobs get fresh ids


def test_user_cancelled_jobs_are_not_restored(build):
    block = threading.Event()
    svc = build(ScriptedSource(block=block))
    svc.create("https://media.example/v", "v1", None)
    waiting = svc.create("https://media.example/v", "v1", None)
    svc.cancel(waiting.id)
    svc.shutdown()  # the running first job is interrupted by closing (restorable); the cancelled one is not

    other = build(ScriptedSource())
    assert wait_for(lambda: len(other.list()) >= 1)
    assert wait_for(lambda: all(j.status in (JobStatus.COMPLETED,) for j in other.list()))
    assert len(other.list()) == 1  # only the first (unfinished at close) came back


# ----------------------------------------------------------------- retry


def test_failed_download_can_be_retried(build):
    gone = AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "gone")
    svc = build(ScriptedSource(failures=[gone]))
    job = svc.create("https://media.example/v", "v1", None)
    assert wait_for(lambda: job.status is JobStatus.FAILED)

    again = svc.retry(job.id)
    assert again.id != job.id
    assert wait_for(lambda: again.status is JobStatus.COMPLETED)


def test_only_failed_or_cancelled_can_be_retried(build):
    svc = build(ScriptedSource())
    job = svc.create("https://media.example/v", "v1", None)
    assert wait_for(lambda: job.status is JobStatus.COMPLETED)
    with pytest.raises(AppError) as exc:
        svc.retry(job.id)
    assert exc.value.status_code == 409
    with pytest.raises(AppError) as unknown:
        svc.retry("00000000-0000-4000-8000-000000000000")
    assert unknown.value.status_code == 404


def test_retry_works_after_a_restart(build):
    gone = AppError(ErrorCode.MEDIA_NOT_AVAILABLE, "gone")
    first = build(ScriptedSource(failures=[gone]))
    job = first.create("https://media.example/v", "v1", None)
    assert wait_for(lambda: job.status is JobStatus.FAILED)
    first.shutdown()

    second = build(ScriptedSource())  # records are gone from memory, but the store remembers
    again = second.retry(job.id)
    assert wait_for(lambda: again.status is JobStatus.COMPLETED)


# ----------------------------------------------------------------- batch


def test_batch_queues_valid_links_and_reports_bad_ones(build):
    svc = build(ScriptedSource())
    results = svc.create_batch(
        [
            "https://media.example/a",
            "https://media.example/a",  # duplicate is ignored
            "not a link",
            "https://media.example/b",
            "   ",
        ]
    )
    assert [r["ok"] for r in results] == [True, False, True]
    assert results[1]["error"]
    assert wait_for(lambda: len([j for j in svc.list() if j.status is JobStatus.COMPLETED]) == 2)


# ------------------------------------------------------------ pick_best


def test_pick_best_prefers_highest_resolution_with_audio_and_supports_audio_mode():
    from backend.app.models.media import MediaFormat

    formats = [
        MediaFormat("a1", "audio", "m4a", None, True, None, False, "a"),
        MediaFormat("v480", "video", "mp4", "480p", True, None, False, "v"),
        MediaFormat("v1080", "video", "mp4", "1080p", False, None, False, "v"),
        MediaFormat("v1080a", "video", "mp4", "1080p", True, None, False, "v"),
    ]
    assert pick_best(formats, "best").id == "v1080a"
    assert pick_best(formats, "audio").id == "a1"
    assert pick_best([], "best") is None
    assert pick_best([formats[1]], "audio").id == "v480"  # no audio-only format: falls back to video
