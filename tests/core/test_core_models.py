import pytest
from core.models.media import MediaFormat, MediaInfo
from core.models.job import Job, JobStatus, InvalidTransition
from core.models.progress import DownloadProgress
from core.models.history import HistoryItem


def test_media_models_creation():
    fmt = MediaFormat(
        id="1080p",
        type="video",
        container="mp4",
        resolution="1080p",
        has_audio=True,
        filesize=50000000,
        requires_merge=False,
        label="1080p Full HD",
    )
    assert fmt.id == "1080p"
    assert fmt.container == "mp4"

    info = MediaInfo(
        source_id="youtube",
        source_label="YouTube",
        url="https://youtube.com/watch?v=123",
        title="Test Video",
        duration=180,
        formats=(fmt,),
        thumbnail="https://example.com/thumb.jpg",
        uploader="Test Channel",
    )
    assert info.title == "Test Video"
    assert len(info.formats) == 1
    assert info.formats[0].id == "1080p"


def test_job_lifecycle_and_transitions():
    job = Job(url="https://example.com/video", title="Video Title", format_id="1080p")
    assert job.status == JobStatus.QUEUED
    assert job.started_at is None
    assert job.completed_at is None

    job.transition(JobStatus.DOWNLOADING)
    assert job.status == JobStatus.DOWNLOADING
    assert job.started_at is not None

    job.transition(JobStatus.PROCESSING)
    assert job.status == JobStatus.PROCESSING

    job.transition(JobStatus.COMPLETED)
    assert job.status == JobStatus.COMPLETED
    assert job.completed_at is not None

    with pytest.raises(InvalidTransition):
        job.transition(JobStatus.DOWNLOADING)


def test_job_cancel_and_fail():
    job1 = Job(url="https://example.com/video", title="Video Title", format_id="1080p")
    assert job1.cancel_if_queued() is True
    assert job1.status == JobStatus.CANCELLED

    job2 = Job(url="https://example.com/video", title="Video Title", format_id="1080p")
    job2.transition(JobStatus.DOWNLOADING)
    job2.fail("DOWNLOAD_ERROR", "Download failed")
    assert job2.status == JobStatus.FAILED
    assert job2.error_code == "DOWNLOAD_ERROR"
    assert job2.error_message == "Download failed"


def test_download_progress():
    p = DownloadProgress(downloaded_bytes=5000, total_bytes=10000, speed_bps=1024.0, eta_seconds=5.0)
    assert p.fraction == 0.5
    assert p.percentage == 50.0

    p_zero = DownloadProgress(downloaded_bytes=0, total_bytes=0)
    assert p_zero.fraction == 0.0
    assert p_zero.percentage == 0.0


def test_history_item():
    item = HistoryItem(
        id="item-1",
        title="Sample Video",
        url="https://example.com/sample",
        format_label="720p · MP4",
        filename="Sample Video.mp4",
        status="completed",
        file_size=1234567,
    )
    assert item.title == "Sample Video"
    assert item.file_size_bytes == 1234567
    d = item.to_dict()
    assert d["id"] == "item-1"
    assert d["status"] == "completed"
