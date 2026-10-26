import pytest
from core.engine import DownloaderEngine
from core.errors.exceptions import AppError, ErrorCode
from core.models.job import Job, JobStatus
from core.models.media import MediaFormat, MediaInfo
from core.models.history import HistoryItem


class MockSourceService:
    def analyze(self, url: str) -> MediaInfo:
        if "bad" in url:
            raise AppError(ErrorCode.INVALID_URL, "Invalid URL provided.")
        fmt = MediaFormat(id="f1", type="video", container="mp4", resolution="720p", has_audio=True)
        return MediaInfo(
            source_id="test",
            source_label="Test",
            url=url,
            title="Mock Title",
            duration=60,
            formats=(fmt,),
        )


class MockJobService:
    def __init__(self):
        self.jobs = {}

    def create(self, *, url, title, format_id, output_format=None):
        job = Job(url=url, title=title, format_id=format_id, output_format=output_format)
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def list_recent(self):
        return list(self.jobs.values())

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job:
            job.mark_cancelled()
            return True
        return False


class MockHistoryService:
    def __init__(self):
        self.items = []

    def list_recent(self, limit=50):
        return self.items[:limit]

    def delete(self, item_id):
        before = len(self.items)
        self.items = [i for i in self.items if i.id != item_id]
        return len(self.items) < before


def test_downloader_engine_analyze():
    source_svc = MockSourceService()
    engine = DownloaderEngine(source_service=source_svc)

    info = engine.analyze("https://example.com/video")
    assert info.title == "Mock Title"
    assert len(info.formats) == 1

    with pytest.raises(AppError) as exc:
        engine.analyze("https://bad.example/video")
    assert exc.value.code == ErrorCode.INVALID_URL


def test_downloader_engine_job_flow():
    job_svc = MockJobService()
    engine = DownloaderEngine(job_service=job_svc)

    job = engine.create_download(url="https://example.com/v", format_id="f1", title="Title")
    assert job.id in job_svc.jobs
    assert engine.get_job(job.id) is job
    assert len(engine.list_jobs()) == 1

    cancelled = engine.cancel_download(job.id)
    assert cancelled is True
    assert job.status == JobStatus.CANCELLED


def test_downloader_engine_history():
    history_svc = MockHistoryService()
    item = HistoryItem(id="h1", title="Item 1", url="https://example.com", format_label="MP4", filename="i1.mp4", status="completed")
    history_svc.items.append(item)

    engine = DownloaderEngine(history_service=history_svc)
    assert len(engine.get_history()) == 1
    assert engine.delete_history("h1") is True
    assert len(engine.get_history()) == 0
