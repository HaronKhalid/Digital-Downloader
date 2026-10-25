import shutil
import threading
import time
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import AppError, ErrorCode, OperationCancelled
from backend.app.models.job import InvalidTransition, Job, JobStatus
from backend.app.models.media import MediaFormat, MediaInfo
from backend.app.services import download_service as ds
from backend.app.services.download_service import DownloadService
from backend.app.services.file_service import (
    cleanup_abandoned_temp,
    job_temp_dir,
    reserve_destination,
)
from backend.app.services.http_client import TransferProgress
from backend.app.services.job_service import AnalysisCache, JobService
from backend.app.services.processing_service import plan_job
from backend.app.services.source_service import SourceService
from backend.app.services.sources.base import MediaSource
from backend.app.utils.urls import validate_url

from .conftest import make_resolver


# ------------------------------------------------------------------ helpers


def F(id, type="video", container="mp4", res="720p", audio=True, size=100_000):
    return MediaFormat(id, type, container, res, audio, size, False, id)


class ScriptedSource(MediaSource):
    """A source whose download behaviour is fully scripted by the test."""

    id, label = "scripted", "Scripted"

    def __init__(self, *, failures=(), block=None, content=None, size=100_000, formats=None, title="Test clip", crash=None):
        self.failures = list(failures)  # exceptions raised by successive download attempts
        self.block = block  # threading.Event: download waits until cancelled/released
        self.content = content or {}  # part index -> Path to copy instead of dummy bytes
        self.size, self.title, self.crash = size, title, crash
        self.formats = formats or (F("v1", size=size),)
        self.calls = 0
        self.started = threading.Event()

    def can_handle(self, url):
        return url.host == "media.example"

    def info(self, url="https://media.example/v"):
        return MediaInfo("scripted", "Scripted", url, self.title, 1, tuple(self.formats))

    def analyze(self, url):
        return self.info(url.url)

    def download(self, url, fmt, dest_dir, part, ctx):
        self.calls += 1
        self.started.set()
        if self.crash:
            raise self.crash
        if self.failures:
            raise self.failures.pop(0)
        dest = dest_dir / f"part{part}.{fmt.container}"
        if part in self.content:
            shutil.copy(self.content[part], dest)
            return dest
        with open(dest, "xb") as fh:
            for i in range(1, 11):
                if ctx.cancel.is_set():
                    raise OperationCancelled
                if self.block is not None and i == 5:
                    while not self.block.is_set():
                        if ctx.cancel.wait(0.02):
                            raise OperationCancelled
                fh.write(b"\0" * (self.size // 10))
                ctx.on_progress(TransferProgress(i * self.size // 10, self.size, 5e5, 1.0))
        return dest


@pytest.fixture
def settings(tmp_path):
    return Settings.load({
        "OUTPUT_DIRECTORY": str(tmp_path / "out"),
        "TEMP_DIRECTORY": str(tmp_path / "temp"),
        "DATABASE_PATH": str(tmp_path / "db" / "h.sqlite3"),
    })


@pytest.fixture
def downloader(settings):
    (settings.temp_directory).mkdir(parents=True, exist_ok=True)
    return DownloadService(settings, retry_delays=(0.0, 0.0))


def make_job(source, fmt_id="v1", output=None):
    info = source.info()
    fmt = next(f for f in info.formats if f.id == fmt_id)
    plan = plan_job(info, fmt, output)
    job = Job(url=info.url, title=info.title, format_id=fmt_id, output_format=output)
    return job, info, plan


def run(downloader, source, job, info, plan):
    downloader.run(job, source, validate_url(info.url, resolve=False), info, plan)


def temp_dirs(settings):
    return [p for p in settings.temp_directory.iterdir()] if settings.temp_directory.exists() else []


def out_files(settings):
    return sorted(p.name for p in settings.output_directory.iterdir()) if settings.output_directory.exists() else []


# ------------------------------------------------------------ state machine


def test_normal_lifecycle_and_timestamps():
    j = Job(url="https://x.example/", title="t", format_id="f", output_format=None)
    assert j.status is JobStatus.QUEUED and j.started_at is None
    j.transition(JobStatus.DOWNLOADING)
    j.transition(JobStatus.PROCESSING)
    assert j.started_at is not None and j.completed_at is None
    j.transition(JobStatus.COMPLETED)
    assert j.completed_at is not None


@pytest.mark.parametrize("terminal", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED])
def test_terminal_states_are_final(terminal):
    j = Job(url="https://x.example/", title="t", format_id="f", output_format=None)
    j.transition(JobStatus.DOWNLOADING)
    j.transition(terminal)
    assert j.completed_at is not None
    for nxt in JobStatus:
        with pytest.raises(InvalidTransition):
            j.transition(nxt)


@pytest.mark.parametrize("target", [JobStatus.PROCESSING, JobStatus.COMPLETED])
def test_queued_job_cannot_skip_ahead(target):
    with pytest.raises(InvalidTransition):
        Job(url="https://x.example/", title="t", format_id="f", output_format=None).transition(target)


def test_progress_never_goes_backwards_or_above_100():
    j = Job(url="https://x.example/", title="t", format_id="f", output_format=None)
    j.update(progress=40)
    j.update(progress=10)
    assert j.progress == 40
    j.update(progress=250)
    assert j.progress == 100


def test_updates_after_completion_are_ignored_and_snapshot_has_no_paths(tmp_path):
    j = Job(url="https://x.example/", title="t", format_id="f", output_format=None)
    j.transition(JobStatus.DOWNLOADING)
    f = tmp_path / "x.mp4"
    f.write_bytes(b"abc")
    j.complete(f)
    j.update(progress=1, stage="nope")
    snap = j.snapshot()
    assert snap["status"] == "completed" and snap["filename"] == "x.mp4" and snap["stage"] == "Completed"
    assert str(tmp_path) not in str(snap)


def test_cancel_if_queued_is_atomic():
    j = Job(url="https://x.example/", title="t", format_id="f", output_format=None)
    assert j.cancel_if_queued() is True and j.status is JobStatus.CANCELLED
    assert j.try_start() is False
    running = Job(url="https://x.example/", title="t", format_id="f", output_format=None)
    assert running.try_start()
    assert running.cancel_if_queued() is False and running.status is JobStatus.DOWNLOADING and running.cancel_event.is_set()


# --------------------------------------------------------------- pipeline


def test_successful_download_saves_file_cleans_temp_and_completes(downloader, settings):
    src = ScriptedSource()
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    snap = job.snapshot()
    assert snap["status"] == "completed" and snap["progress"] == 100 and snap["filename"] == "Test clip.mp4"
    assert out_files(settings) == ["Test clip.mp4"]
    assert (settings.output_directory / "Test clip.mp4").stat().st_size == 100_000
    assert temp_dirs(settings) == []


def test_hostile_title_cannot_escape_the_output_directory(downloader, settings, tmp_path):
    src = ScriptedSource(title="../../../etc/evil\\..\\x:y*z?.exe")
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.COMPLETED
    produced = list(tmp_path.rglob("*evil*"))
    assert len(produced) == 1 and produced[0].parent == settings.output_directory.resolve()
    assert produced[0].suffix == ".mp4"


def test_same_title_never_overwrites_an_existing_file(downloader, settings):
    names = []
    for _ in range(3):
        src = ScriptedSource()
        job, info, plan = make_job(src)
        run(downloader, src, job, info, plan)
        names.append(job.filename)
    assert names == ["Test clip.mp4", "Test clip (1).mp4", "Test clip (2).mp4"]


def test_progress_samples_are_monotonic_and_bounded(downloader):
    src = ScriptedSource()
    job, info, plan = make_job(src)
    seen = []
    original = job.update
    job.update = lambda **kw: (original(**kw), seen.append(job.progress))[0]
    run(downloader, src, job, info, plan)
    assert seen == sorted(seen) and 0 <= min(seen) and max(seen) <= 100


def test_transient_failures_are_retried_then_succeed(downloader, settings):
    boom = lambda: AppError(ErrorCode.SOURCE_UNAVAILABLE, "lost", reason="connection_lost")
    src = ScriptedSource(failures=[boom(), boom()])
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.COMPLETED and src.calls == 3
    assert out_files(settings) == ["Test clip.mp4"]


def test_retries_are_bounded(downloader, settings):
    boom = lambda: AppError(ErrorCode.TIMEOUT, "slow", reason="read_timeout")
    src = ScriptedSource(failures=[boom(), boom(), boom(), boom()])
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.FAILED and job.error_code == "TIMEOUT" and src.calls == 3
    assert temp_dirs(settings) == [] and out_files(settings) == []


@pytest.mark.parametrize("reason,code", [("http_404", ErrorCode.MEDIA_NOT_AVAILABLE), ("http_403", ErrorCode.MEDIA_NOT_AVAILABLE), ("bad", ErrorCode.FORMAT_NOT_AVAILABLE)])
def test_deterministic_failures_are_not_retried(downloader, reason, code):
    src = ScriptedSource(failures=[AppError(code, "no", reason=reason)] * 3)
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.FAILED and src.calls == 1 and job.error_code == code.value


def test_cancel_during_download_stops_cleans_up_and_leaves_no_file(downloader, settings):
    block = threading.Event()
    src = ScriptedSource(block=block)
    job, info, plan = make_job(src)
    t = threading.Thread(target=run, args=(downloader, src, job, info, plan))
    t.start()
    assert src.started.wait(5)
    time.sleep(0.15)
    assert temp_dirs(settings), "job directory should exist while running"
    job.cancel_event.set()
    t.join(5)
    assert not t.is_alive() and job.status is JobStatus.CANCELLED
    assert temp_dirs(settings) == [] and out_files(settings) == []


def test_job_cancelled_while_queued_never_starts(downloader, settings):
    src = ScriptedSource()
    job, info, plan = make_job(src)
    assert job.cancel_if_queued()
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.CANCELLED and src.calls == 0 and temp_dirs(settings) == []


def test_cancel_flag_set_just_before_start_is_honoured(downloader, settings):
    src = ScriptedSource()
    job, info, plan = make_job(src)
    job.cancel_event.set()  # cancel arrived but status is still QUEUED
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.CANCELLED and src.calls == 0


def test_unexpected_crash_becomes_a_clean_failure(downloader, settings):
    src = ScriptedSource(crash=RuntimeError("secret internal detail /home/user/x"))
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    snap = job.snapshot()
    assert snap["status"] == "failed" and snap["error"]["code"] == "UNKNOWN_ERROR"
    assert "secret" not in snap["error"]["message"] and "/home" not in snap["error"]["message"]
    assert temp_dirs(settings) == []


def test_low_disk_space_is_refused_before_downloading(downloader, settings, monkeypatch):
    class Usage:
        free = 10 * 1024**2

    monkeypatch.setattr(ds.shutil, "disk_usage", lambda p: Usage())
    src = ScriptedSource(size=2 * 1024**3)
    job, info, plan = make_job(src)
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.FAILED and job.error_code == "DISK_SPACE_LOW"
    assert "Required:" in job.error_message and "available:" in job.error_message
    assert src.calls == 0 and temp_dirs(settings) == []


def test_file_larger_than_the_configured_maximum_is_refused(settings):
    tiny = Settings.load({**{"OUTPUT_DIRECTORY": str(settings.output_directory), "TEMP_DIRECTORY": str(settings.temp_directory), "MAX_DOWNLOAD_GB": "1"}})
    svc = DownloadService(tiny, retry_delays=(0, 0))
    src = ScriptedSource(size=3 * 1024**3)
    job, info, plan = make_job(src)
    run(svc, src, job, info, plan)
    assert job.error_code == "MEDIA_NOT_AVAILABLE" and src.calls == 0


def test_unusable_output_folder_gives_a_permission_error(tmp_path, settings):
    blocker = tmp_path / "iam-a-file"
    blocker.write_text("x")
    bad = Settings.load({"OUTPUT_DIRECTORY": str(blocker / "sub"), "TEMP_DIRECTORY": str(settings.temp_directory)})
    src = ScriptedSource()
    job, info, plan = make_job(src)
    run(DownloadService(bad, retry_delays=(0, 0)), src, job, info, plan)
    assert job.error_code == "PERMISSION_DENIED" and "output folder" in job.error_message


def test_a_running_job_is_isolated_from_other_jobs_cleanup(downloader, settings):
    block = threading.Event()
    slow = ScriptedSource(block=block)
    slow_job, slow_info, slow_plan = make_job(slow)
    t = threading.Thread(target=run, args=(downloader, slow, slow_job, slow_info, slow_plan))
    t.start()
    assert slow.started.wait(5)
    time.sleep(0.15)
    slow_dir = job_temp_dir(settings.temp_directory, slow_job.id)
    assert (slow_dir / "part0.mp4").exists()

    quick = ScriptedSource(title="Other")
    qjob, qinfo, qplan = make_job(quick)
    run(downloader, quick, qjob, qinfo, qplan)
    assert qjob.status is JobStatus.COMPLETED
    assert (slow_dir / "part0.mp4").exists(), "finishing one job must not touch another job's files"

    block.set()
    t.join(5)
    assert slow_job.status is JobStatus.COMPLETED and temp_dirs(settings) == []


# ------------------------------------------------------------ real FFmpeg


HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.fixture(scope="module")
def media_files(tmp_path_factory):
    import subprocess

    d = tmp_path_factory.mktemp("jobmedia")
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run([*base, "-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "v.mp4")], check=True)
    subprocess.run([*base, "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:a", "aac", str(d / "a.m4a")], check=True)
    return d


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_video_and_audio_parts_are_merged_through_the_processing_state(downloader, settings, media_files):
    formats = (F("v-only", audio=False, size=0), F("a-only", "audio", "m4a", None, True, 0))
    src = ScriptedSource(formats=formats, content={0: media_files / "v.mp4", 1: media_files / "a.m4a"})
    job, info, plan = make_job(src, "v-only")
    states = []
    original = job.transition
    job.transition = lambda s: (states.append(s), original(s))[1]
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.COMPLETED and JobStatus.PROCESSING in states
    import json, subprocess

    out = settings.output_directory / job.filename
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(out)], capture_output=True, text=True).stdout)["streams"]
    assert sorted(s["codec_type"] for s in streams) == ["audio", "video"]
    assert temp_dirs(settings) == []


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_corrupt_download_fails_in_processing_and_cleans_up(downloader, settings, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not media" * 50)
    formats = (F("v1", audio=True, size=0),)
    src = ScriptedSource(formats=formats, content={0: bad})
    job, info, plan = make_job(src, "v1", output="mkv")
    run(downloader, src, job, info, plan)
    assert job.status is JobStatus.FAILED and job.error_code == "PROCESSING_FAILED"
    assert temp_dirs(settings) == [] and out_files(settings) == []


# --------------------------------------------------------- file helpers


def test_reserve_destination_is_exclusive(tmp_path):
    a = reserve_destination(tmp_path, "x.mp4")
    b = reserve_destination(tmp_path, "x.mp4")
    assert a.name == "x.mp4" and b.name == "x (1).mp4" and a.exists() and b.exists()


def test_reserve_destination_is_safe_under_contention(tmp_path):
    results = []
    threads = [threading.Thread(target=lambda: results.append(reserve_destination(tmp_path, "c.mp3"))) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len({p.name for p in results}) == 12


def test_abandoned_temp_cleanup_only_touches_our_own_old_job_dirs(tmp_path):
    import os, uuid

    old = tmp_path / f"job-{uuid.uuid4()}"
    old.mkdir()
    (old / "part0.mp4").write_text("x")
    fresh = tmp_path / f"job-{uuid.uuid4()}"
    fresh.mkdir()
    stranger = tmp_path / "my-important-folder"
    stranger.mkdir()
    lookalike = tmp_path / "job-not-a-uuid"
    lookalike.mkdir()
    outside = tmp_path.parent / f"outside-{uuid.uuid4()}"
    outside.mkdir()
    link = tmp_path / f"job-{uuid.uuid4()}"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        link = None
    ancient = time.time() - 7200
    for p in (old, stranger, lookalike):
        os.utime(p, (ancient, ancient))  # old enough to be eligible by age, so only the NAME protects them
    if link is not None:
        os.utime(link, (ancient, ancient), follow_symlinks=False)

    assert cleanup_abandoned_temp(tmp_path, older_than_seconds=600) == 1
    assert not old.exists() and fresh.exists() and stranger.exists() and lookalike.exists() and outside.exists()
    if link is not None:
        assert link.is_symlink()


# ------------------------------------------------------------ job service


@pytest.fixture
def service(settings, downloader, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", make_resolver("93.184.216.34"))
    holder = {}

    def build(source):
        sources = SourceService([source])
        svc = JobService(settings, sources, downloader, AnalysisCache())
        svc.start()
        holder["svc"] = svc
        return svc

    yield build
    if "svc" in holder:
        holder["svc"].shutdown()


def wait_for(predicate, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_service_runs_a_job_to_completion(service, settings):
    svc = service(ScriptedSource())
    job = svc.create("https://media.example/v", "v1", None)
    assert wait_for(lambda: job.status is JobStatus.COMPLETED)
    assert svc.get(job.id) is job and out_files(settings) == ["Test clip.mp4"]


def test_service_only_accepts_format_ids_that_analysis_returned(service):
    svc = service(ScriptedSource())
    for bad in ("nope", "v1; rm -rf /", "--exec=calc", "../v1", ""):
        with pytest.raises(AppError) as exc:
            svc.create("https://media.example/v", bad, None)
        assert exc.value.code is ErrorCode.FORMAT_NOT_AVAILABLE


def test_service_rejects_bad_urls_unsupported_sites_and_bad_outputs(service):
    svc = service(ScriptedSource())
    with pytest.raises(AppError) as exc:
        svc.create("http://127.0.0.1/x", "v1", None)
    assert exc.value.code is ErrorCode.INVALID_URL
    with pytest.raises(AppError) as exc:
        svc.create("https://other.example/x", "v1", None)
    assert exc.value.code is ErrorCode.UNSUPPORTED_SOURCE
    with pytest.raises(AppError) as exc:
        svc.create("https://media.example/v", "v1", "exe")
    assert exc.value.code is ErrorCode.FORMAT_NOT_AVAILABLE


@pytest.mark.parametrize("bad", ["nope", "../../etc/passwd", "", "123", "3F2B8C1E-5D4A-4B6F-9A1C-0E7D2F4B8A91", "00000000-0000-4000-8000-000000000000"])
def test_unknown_or_malformed_job_ids_are_plain_not_found(service, bad):
    svc = service(ScriptedSource())
    with pytest.raises(AppError) as exc:
        svc.get(bad)
    assert exc.value.code is ErrorCode.NOT_FOUND and exc.value.status_code == 404


def test_queued_job_waits_for_the_running_one_and_can_be_cancelled(service, settings):
    block = threading.Event()
    src = ScriptedSource(block=block)
    svc = service(src)  # max_parallel_jobs defaults to 1
    first = svc.create("https://media.example/v", "v1", None)
    assert src.started.wait(5)
    second = svc.create("https://media.example/v", "v1", None)
    time.sleep(0.2)
    assert first.status is JobStatus.DOWNLOADING and second.status is JobStatus.QUEUED
    svc.cancel(second.id)
    assert second.status is JobStatus.CANCELLED
    block.set()
    assert wait_for(lambda: first.status is JobStatus.COMPLETED)
    assert src.calls == 1, "the cancelled job must never have started"


def test_cancelling_a_running_job(service, settings):
    block = threading.Event()
    src = ScriptedSource(block=block)
    svc = service(src)
    job = svc.create("https://media.example/v", "v1", None)
    assert src.started.wait(5)
    svc.cancel(job.id)
    assert wait_for(lambda: job.status is JobStatus.CANCELLED)
    assert wait_for(lambda: temp_dirs(settings) == []) and out_files(settings) == []


def test_cancelling_a_finished_job_is_a_conflict(service):
    svc = service(ScriptedSource())
    job = svc.create("https://media.example/v", "v1", None)
    assert wait_for(lambda: job.status is JobStatus.COMPLETED)
    with pytest.raises(AppError) as exc:
        svc.cancel(job.id)
    assert exc.value.status_code == 409


def test_shutdown_cancels_running_work_and_waits(service, settings):
    block = threading.Event()
    src = ScriptedSource(block=block)
    svc = service(src)
    job = svc.create("https://media.example/v", "v1", None)
    assert src.started.wait(5)
    svc.shutdown()
    assert job.status is JobStatus.CANCELLED and temp_dirs(settings) == []


def test_analysis_cache_expires_and_is_bounded():
    cache = AnalysisCache(ttl=0.05, max_entries=2)
    infos = [MediaInfo("s", "S", f"https://x.example/{i}", "t", 1, ()) for i in range(3)]
    for i in infos:
        cache.put(i)
    assert cache.get(infos[0].url) is None and cache.get(infos[2].url) is infos[2]
    time.sleep(0.08)
    assert cache.get(infos[2].url) is None
