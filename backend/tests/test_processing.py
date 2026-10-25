import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from backend.app.core.errors import AppError, ErrorCode, OperationCancelled
from backend.app.models.media import MediaFormat, MediaInfo
from backend.app.services.processing_service import build_command, plan_job, run_processing

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")


def F(id, type, container, res=None, audio=True, size=None):
    return MediaFormat(id, type, container, res, audio, size, False, id)


def info(*formats):
    return MediaInfo("t", "T", "https://x.example/", "Title", 1, tuple(formats))


V_MP4 = F("v-mp4", "video", "mp4", "720p", audio=False, size=1000)
V_WEBM = F("v-webm", "video", "webm", "720p", audio=False, size=900)
AV_MP4 = F("av-mp4", "video", "mp4", "480p", audio=True, size=500)
A_M4A = F("a-m4a", "audio", "m4a", size=200)
A_OPUS = F("a-opus", "audio", "webm", size=150)
A_MP3 = F("a-mp3", "audio", "mp3", size=100)
CATALOG = info(V_MP4, V_WEBM, AV_MP4, A_M4A, A_OPUS, A_MP3)


# ------------------------------------------------------------------ planning


def test_audio_kept_as_is_or_converted():
    p = plan_job(CATALOG, A_M4A, None)
    assert (p.operation, p.output_ext, p.parts) == ("none", "m4a", (A_M4A,))
    assert plan_job(CATALOG, A_M4A, "mp3").operation == "convert_audio"
    assert plan_job(CATALOG, A_M4A, "m4a").operation == "none"


def test_video_with_audio_is_kept_or_remuxed():
    assert plan_job(CATALOG, AV_MP4, None).operation == "none"
    p = plan_job(CATALOG, AV_MP4, "mkv")
    assert (p.operation, p.output_ext) == ("remux", "mkv")


def test_video_only_is_merged_with_a_compatible_audio_stream():
    p = plan_job(CATALOG, V_MP4, None)
    assert (p.operation, p.output_ext, [f.id for f in p.parts]) == ("merge", "mp4", ["v-mp4", "a-m4a"])
    p = plan_job(CATALOG, V_WEBM, None)
    assert (p.output_ext, [f.id for f in p.parts]) == ("webm", ["v-webm", "a-opus"])
    assert p.expected_bytes == 900 + 150


def test_incompatible_pair_falls_back_to_mkv():
    only_opus = info(V_MP4, A_OPUS)
    assert plan_job(only_opus, V_MP4, None).output_ext == "mkv"


def test_explicit_output_format_is_honoured_for_merges():
    p = plan_job(CATALOG, V_MP4, "webm")
    assert (p.operation, p.output_ext) == ("merge", "webm") and p.parts[1].container == "webm"


def test_video_only_with_no_audio_available_is_delivered_as_video():
    p = plan_job(info(V_MP4), V_MP4, None)
    assert (p.operation, [f.id for f in p.parts]) == ("none", ["v-mp4"])


@pytest.mark.parametrize(
    "fmt,out",
    [(AV_MP4, "mp3"), (A_M4A, "mp4"), (AV_MP4, "exe"), (A_M4A, "../x"), (AV_MP4, "flv"), (A_M4A, "")],
)
def test_impossible_output_formats_are_rejected(fmt, out):
    with pytest.raises(AppError) as exc:
        plan_job(CATALOG, fmt, out)
    assert exc.value.code is ErrorCode.FORMAT_NOT_AVAILABLE


def test_source_container_outside_the_allow_list_needs_an_explicit_output():
    flv = F("flv", "video", "flv", "360p", audio=True)
    with pytest.raises(AppError):
        plan_job(info(flv), flv, None)
    assert plan_job(info(flv), flv, "mp4").operation == "remux"


# ------------------------------------------------------------ command shape


def test_ffmpeg_command_is_a_clean_argument_list(tmp_path):
    plan = plan_job(CATALOG, V_MP4, None)
    cmd = build_command("/usr/bin/ffmpeg", plan, [tmp_path / "part0.mp4", tmp_path / "part1.m4a"], tmp_path / "out.mp4", transcode=False)
    assert isinstance(cmd, list) and cmd[0] == "/usr/bin/ffmpeg" and cmd[-1] == str(tmp_path / "out.mp4")
    assert "-n" in cmd and "-nostdin" in cmd and cmd.count("-i") == 2
    assert all(Path(cmd[i + 1]).is_absolute() for i, a in enumerate(cmd) if a == "-i")
    assert "-c" in cmd and "copy" in cmd


# --------------------------------------------------------- real FFmpeg runs


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return [(s["codec_type"], s["codec_name"]) for s in json.loads(out)["streams"]]


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    src = ["-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=10"]
    tone = ["-f", "lavfi", "-i", "sine=f=440:d=1"]
    ff(*src, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "v.mp4"))
    ff(*src, "-c:v", "libvpx-vp9", str(d / "v.webm"))
    ff(*tone, "-c:a", "aac", str(d / "a.m4a"))
    ff(*src, *tone, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "av.mp4"))
    return d


@pytest.fixture
def job_dir(tmp_path):
    d = tmp_path / "job"
    d.mkdir()
    return d


def run(plan, inputs, job_dir, **kw):
    fractions = []
    out = run_processing(plan, inputs, job_dir, duration=1, cancel=kw.pop("cancel", threading.Event()), on_fraction=fractions.append, **kw)
    return out, fractions


@needs_ffmpeg
def test_merge_video_and_audio_by_stream_copy(media, job_dir):
    plan = plan_job(CATALOG, V_MP4, None)
    out, fractions = run(plan, [media / "v.mp4", media / "a.m4a"], job_dir)
    assert out == job_dir / "out.mp4" and sorted(probe(out)) == [("audio", "aac"), ("video", "h264")]
    assert fractions[-1] == 1.0


@needs_ffmpeg
def test_incompatible_copy_falls_back_to_reencoding(media, job_dir):
    plan = plan_job(CATALOG, V_MP4, "webm")  # h264 + aac cannot be copied into webm
    out, _ = run(plan, [media / "v.mp4", media / "a.m4a"], job_dir)
    assert sorted(probe(out)) == [("audio", "opus"), ("video", "vp9")]


@needs_ffmpeg
def test_remux_to_mkv_keeps_streams(media, job_dir):
    out, _ = run(plan_job(CATALOG, AV_MP4, "mkv"), [media / "av.mp4"], job_dir)
    assert sorted(probe(out)) == [("audio", "aac"), ("video", "h264")]


@needs_ffmpeg
@pytest.mark.parametrize("target,codec,source_fmt", [("mp3", "mp3", A_M4A), ("opus", "opus", A_MP3), ("m4a", "aac", A_MP3)])
def test_audio_conversion(media, job_dir, target, codec, source_fmt):
    src = media / "av.mp4"  # audio track extracted from a file that also has video
    plan = plan_job(CATALOG, source_fmt, target)  # source format differs from the target, so conversion is real
    out, _ = run(plan, [src], job_dir)
    assert out.suffix == f".{target}" and probe(out) == [("audio", codec)]


@needs_ffmpeg
def test_corrupt_input_fails_cleanly_and_leaves_no_output(job_dir):
    bad = job_dir / "part0.mp4"
    bad.write_bytes(b"this is not a video" * 100)
    with pytest.raises(AppError) as exc:
        run(plan_job(CATALOG, AV_MP4, "mkv"), [bad], job_dir)
    assert exc.value.code is ErrorCode.PROCESSING_FAILED and "ffmpeg" not in exc.value.message.lower()
    assert not (job_dir / "out.mkv").exists()


@needs_ffmpeg
def test_cancellation_before_processing_raises_cancelled(media, job_dir):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OperationCancelled):
        run(plan_job(CATALOG, AV_MP4, "mkv"), [media / "av.mp4"], job_dir, cancel=cancel)


def test_missing_ffmpeg_gives_actionable_error(job_dir, monkeypatch):
    monkeypatch.setattr("backend.app.services.processing_service.find_ffmpeg", lambda: None)
    with pytest.raises(AppError) as exc:
        run(plan_job(CATALOG, AV_MP4, "mkv"), [job_dir / "x.mp4"], job_dir)
    assert exc.value.code is ErrorCode.FFMPEG_NOT_FOUND and "Install FFmpeg" in exc.value.message


def test_running_a_no_op_plan_is_refused(job_dir):
    with pytest.raises(ValueError):
        run(plan_job(CATALOG, AV_MP4, None), [job_dir / "x.mp4"], job_dir)
