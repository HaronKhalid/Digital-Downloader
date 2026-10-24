import json

import pytest

from backend.app.core.errors import AppError, ErrorCode
from backend.app.services.http_client import HttpResponse
from backend.app.services.source_service import SourceService, sniff_image_type
from backend.app.services.sources.direct import DirectFileSource
from backend.app.services.sources.ytdlp import YtDlpSource, map_error, normalize_info
from backend.app.utils.urls import validate_url

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def vurl(text):
    return validate_url(text, resolve=False)


# ------------------------------------------------------------- fake client


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, max_body=0):
        self.calls.append((method, url, dict(headers or {}), max_body))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(status=200, headers=None, body=b"", url="https://x.example/"):
    return HttpResponse(status, {k.lower(): v for k, v in (headers or {}).items()}, body, url)


# --------------------------------------------------------------- direct files


def test_direct_source_detects_by_extension_ignoring_query():
    src = DirectFileSource(FakeClient())
    assert src.can_handle(vurl("https://cdn.example/a/clip.MP4?token=1"))
    assert src.can_handle(vurl("https://cdn.example/a/song.flac"))
    assert not src.can_handle(vurl("https://cdn.example/a/page.html"))
    assert not src.can_handle(vurl("https://cdn.example/a/run.exe"))
    assert not src.can_handle(vurl("https://cdn.example/watch?v=clip.mp4"))


def test_direct_source_reads_size_and_type_from_head():
    client = FakeClient(resp(200, {"Content-Type": "video/mp4", "Content-Length": "2048"}))
    info = DirectFileSource(client).analyze(vurl("https://cdn.example/My%20Holiday.mp4"))
    assert (info.title, info.source_id, info.duration) == ("My Holiday", "direct", None)
    f = info.formats[0]
    assert (f.type, f.container, f.filesize, f.has_audio) == ("video", "mp4", 2048, True)
    assert client.calls[0][0] == "HEAD"


def test_direct_source_marks_audio_files():
    client = FakeClient(resp(200, {"Content-Type": "audio/mpeg", "Content-Length": "10"}))
    assert DirectFileSource(client).analyze(vurl("https://cdn.example/s.mp3")).formats[0].type == "audio"


def test_direct_source_falls_back_to_one_byte_range_request_when_head_refused():
    client = FakeClient(
        resp(405),
        resp(206, {"Content-Type": "video/webm", "Content-Range": "bytes 0-0/987654"}),
    )
    info = DirectFileSource(client).analyze(vurl("https://cdn.example/c.webm"))
    assert info.formats[0].filesize == 987654
    method, _, headers, max_body = client.calls[1]
    assert method == "GET" and headers == {"Range": "bytes=0-0"} and max_body == 0


@pytest.mark.parametrize(
    "response,code",
    [
        (resp(404), ErrorCode.MEDIA_NOT_AVAILABLE),
        (resp(410), ErrorCode.MEDIA_NOT_AVAILABLE),
        (resp(401), ErrorCode.MEDIA_NOT_AVAILABLE),
        (resp(500), ErrorCode.SOURCE_UNAVAILABLE),
        (resp(200, {"Content-Type": "text/html; charset=utf-8"}), ErrorCode.MEDIA_NOT_AVAILABLE),
        (resp(200, {"Content-Type": "application/json"}), ErrorCode.MEDIA_NOT_AVAILABLE),
    ],
)
def test_direct_source_error_categories(response, code):
    with pytest.raises(AppError) as exc:
        DirectFileSource(FakeClient(response)).analyze(vurl("https://cdn.example/c.mp4"))
    assert exc.value.code is code


def test_forbidden_file_never_triggers_retry_with_credentials():
    client = FakeClient(resp(403), resp(403))
    with pytest.raises(AppError) as exc:
        DirectFileSource(client).analyze(vurl("https://cdn.example/c.mp4"))
    assert "sign-in" in exc.value.message
    assert all("authorization" not in {k.lower() for k in c[2]} for c in client.calls)


# ----------------------------------------------------------------- yt-dlp

SAMPLE = {
    "title": "Public domain film",
    "duration": 125.4,
    "thumbnail": "https://archive.org/services/img/x",
    "formats": [
        {"format_id": "webm-480", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 480, "filesize_approx": 5_000_000, "protocol": "https"},
        {"format_id": "mp3-128", "ext": "mp3", "vcodec": "none", "acodec": "mp3", "abr": 128.0, "protocol": "https"},
        {"format_id": "mp4-720", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "height": 720, "fps": 24, "filesize": 10_000_000, "protocol": "https"},
        {"format_id": "mp4-720p60", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "height": 720, "fps": 60, "protocol": "https"},
        {"format_id": "drm-1080", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "height": 1080, "has_drm": True, "protocol": "https"},
        {"format_id": "maybe-drm", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "height": 1080, "has_drm": "maybe", "protocol": "https"},
        {"format_id": "sb0", "ext": "mhtml", "format_note": "storyboard", "protocol": "mhtml", "vcodec": "none", "acodec": "none"},
        {"format_id": "--exec=calc", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "height": 1, "protocol": "https"},
        {"format_id": "a b", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "height": 1, "protocol": "https"},
        {"format_id": "rtmp-1", "ext": "flv", "vcodec": "h264", "acodec": "aac", "height": 360, "protocol": "rtmp"},
        {"format_id": "badext", "ext": "../../etc", "vcodec": "h264", "acodec": "aac", "height": 360},
        "garbage", None, 7,
    ],
}


def norm(info=SAMPLE):
    return normalize_info(info, source_id="ytdlp", source_label="Web media", url="https://archive.org/details/x")


def test_normalization_keeps_only_safe_downloadable_formats_in_useful_order():
    info = norm()
    assert [f.id for f in info.formats] == ["mp4-720p60", "mp4-720", "webm-480", "mp3-128"]
    assert (info.title, info.duration) == ("Public domain film", 125)
    assert info.thumbnail_url == "https://archive.org/services/img/x"


def test_drm_flagged_streams_are_never_offered():
    ids = {f.id for f in norm().formats}
    assert not ids & {"drm-1080", "maybe-drm"}


def test_format_details():
    by_id = {f.id: f for f in norm().formats}
    assert by_id["mp4-720"].resolution == "720p" and by_id["mp4-720"].has_audio and by_id["mp4-720"].filesize == 10_000_000
    assert by_id["mp4-720p60"].resolution == "720p60"
    assert by_id["webm-480"].has_audio is False and by_id["webm-480"].filesize_approximate and "no audio" in by_id["webm-480"].label
    assert by_id["mp3-128"].type == "audio" and by_id["mp3-128"].resolution is None and "128 kbps" in by_id["mp3-128"].label


def test_format_ids_are_safe_to_hand_to_a_downloader():
    import re

    assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.=\-]*", f.id) for f in norm().formats)


def test_non_https_thumbnail_is_dropped():
    assert norm({**SAMPLE, "thumbnail": "http://insecure.example/t.jpg"}).thumbnail_url is None
    assert norm({**SAMPLE, "thumbnail": "javascript:alert(1)"}).thumbnail_url is None


def test_missing_title_gets_placeholder_and_long_title_is_capped():
    assert norm({**SAMPLE, "title": "  "}).title == "Untitled"
    assert len(norm({**SAMPLE, "title": "x" * 999}).title) == 200


def test_single_entry_playlist_is_unwrapped_but_collections_are_refused():
    assert norm({"_type": "playlist", "entries": [SAMPLE]}).title == "Public domain film"
    with pytest.raises(AppError) as exc:
        norm({"_type": "playlist", "entries": [SAMPLE, SAMPLE]})
    assert exc.value.code is ErrorCode.UNSUPPORTED_SOURCE


def test_live_streams_and_formatless_results_are_refused():
    with pytest.raises(AppError):
        norm({**SAMPLE, "is_live": True})
    with pytest.raises(AppError) as exc:
        norm({"title": "x", "formats": [SAMPLE["formats"][4]]})  # only a DRM format
    assert exc.value.reason == "no_formats"


@pytest.mark.parametrize("junk", [None, [], "str", 5])
def test_non_object_json_is_refused(junk):
    with pytest.raises(AppError):
        norm(junk)


def runner_returning(code=0, out=b"", err=b""):
    seen = {}

    def run(args, timeout):
        seen["args"], seen["timeout"] = args, timeout
        return code, out, err

    return run, seen


def test_ytdlp_source_domain_matching_is_exact_not_substring():
    src = YtDlpSource(frozenset({"archive.org"}))
    assert src.can_handle(vurl("https://archive.org/details/x"))
    assert src.can_handle(vurl("https://ia800.us.archive.org/x"))
    assert not src.can_handle(vurl("https://evilarchive.org/details/x"))
    assert not src.can_handle(vurl("https://archive.org.evil.example/details/x"))
    assert not src.can_handle(vurl("https://example.com/archive.org"))


def test_command_line_is_an_argument_list_with_url_after_double_dash():
    src = YtDlpSource(frozenset({"archive.org"}))
    url = "https://archive.org/details/x?a=1&b=$(whoami)"
    cmd = src.build_command(url)
    assert isinstance(cmd, list) and cmd[-2:] == ["--", url]
    for flag in ("--ignore-config", "--no-plugin-dirs", "--dump-single-json", "--no-playlist", "--no-exec"):
        assert flag in cmd
    assert not any(a.startswith("--cookies") or a in ("--netrc", "--username", "--password") for a in cmd)
    assert cmd.count(url) == 1


def test_ytdlp_source_success_path():
    run, seen = runner_returning(out=json.dumps(SAMPLE).encode())
    info = YtDlpSource(frozenset({"archive.org"}), runner=run, timeout=12).analyze(vurl("https://archive.org/details/x"))
    assert info.source_id == "ytdlp" and len(info.formats) == 4 and seen["timeout"] == 12


@pytest.mark.parametrize(
    "stderr,code",
    [
        ("ERROR: Unsupported URL: https://x", ErrorCode.UNSUPPORTED_SOURCE),
        ("ERROR: [x] 1: Video unavailable", ErrorCode.MEDIA_NOT_AVAILABLE),
        ("ERROR: Unable to download webpage: HTTP Error 404: Not Found", ErrorCode.MEDIA_NOT_AVAILABLE),
        ("ERROR: Sign in to confirm you're not a bot", ErrorCode.MEDIA_NOT_AVAILABLE),
        ("ERROR: This video is private", ErrorCode.MEDIA_NOT_AVAILABLE),
        ("ERROR: HTTP Error 403: Forbidden", ErrorCode.MEDIA_NOT_AVAILABLE),
        ("ERROR: This video is DRM protected", ErrorCode.MEDIA_NOT_AVAILABLE),
        ("ERROR: Unable to download webpage: Failed to resolve 'archive.org'", ErrorCode.SOURCE_UNAVAILABLE),
        ("ERROR: The read operation timed out", ErrorCode.TIMEOUT),
        ("ERROR: something strange", ErrorCode.SOURCE_UNAVAILABLE),
    ],
)
def test_extractor_failures_map_to_categories_without_leaking_raw_output(stderr, code):
    err = map_error(stderr)
    assert err.code is code
    assert "yt-dlp" not in err.message.lower() or "isn't installed" in err.message
    assert "ERROR:" not in err.message and "https://x" not in err.message


def test_failure_exit_code_wins_even_when_stdout_is_null():
    run, _ = runner_returning(1, b"null\n", b"ERROR: Video unavailable")
    with pytest.raises(AppError) as exc:
        YtDlpSource(frozenset({"archive.org"}), runner=run).analyze(vurl("https://archive.org/details/x"))
    assert exc.value.code is ErrorCode.MEDIA_NOT_AVAILABLE


def test_garbage_or_oversized_output_is_refused():
    for out in (b"<html>", b"", b"{" * 5):
        run, _ = runner_returning(out=out)
        with pytest.raises(AppError):
            YtDlpSource(frozenset({"archive.org"}), runner=run).analyze(vurl("https://archive.org/details/x"))


def test_real_extractor_subprocess_fails_cleanly_for_unreachable_item():
    """Runs the real yt-dlp subprocess. Offline it can't resolve the host; online the item doesn't exist.
    Either way we must get a categorized AppError, never a crash or raw output."""
    pytest.importorskip("yt_dlp")
    with pytest.raises(AppError) as exc:
        YtDlpSource(frozenset({"archive.org"}), timeout=40).analyze(vurl("https://archive.org/details/personal-media-test-does-not-exist-0000"))
    assert exc.value.code in {ErrorCode.SOURCE_UNAVAILABLE, ErrorCode.MEDIA_NOT_AVAILABLE, ErrorCode.TIMEOUT, ErrorCode.UNSUPPORTED_SOURCE}
    assert "Traceback" not in exc.value.message and "ERROR" not in exc.value.message


# ----------------------------------------------------------- source service


class StubSource:
    id, label = "stub", "Stub"

    def __init__(self, handles, thumb=None):
        self.handles, self.thumb = handles, thumb

    def can_handle(self, url):
        return self.handles in url.url

    def analyze(self, url):
        from backend.app.models.media import MediaInfo

        return MediaInfo("stub", "Stub", url.url, "T", 1, (), thumbnail_url=self.thumb)


def test_unknown_site_is_unsupported_with_helpful_message():
    with pytest.raises(AppError) as exc:
        SourceService([StubSource("nothing")]).analyze(vurl("https://example.com/page"))
    assert exc.value.code is ErrorCode.UNSUPPORTED_SOURCE and "direct link" in exc.value.message


def test_first_matching_source_wins_so_direct_files_skip_the_extractor():
    first, second = StubSource("a.example"), StubSource("a.example")
    svc = SourceService([first, second])
    assert svc.detect(vurl("https://a.example/x.mp4")) is first


@pytest.mark.parametrize(
    "body,expected",
    [
        (JPEG, "data:image/jpeg;base64,"),
        (PNG, "data:image/png;base64,"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", None),
        (b"<html><script>alert(1)</script></html>", None),
        (b"", None),
    ],
)
def test_thumbnails_are_embedded_only_when_content_is_a_real_raster_image(body, expected):
    client = FakeClient(resp(200, {"Content-Type": "image/jpeg"}, body))  # header lies for non-images
    info = SourceService([StubSource("t.example", "https://t.example/i.jpg")], http_client=client).analyze(vurl("https://t.example/x"))
    assert (info.thumbnail is None) if expected is None else info.thumbnail.startswith(expected)


def test_thumbnail_problems_never_fail_the_analysis():
    for item in (AppError(ErrorCode.TIMEOUT, "slow"), resp(404, body=b"")):
        client = FakeClient(item)
        info = SourceService([StubSource("t.example", "https://t.example/i.jpg")], http_client=client).analyze(vurl("https://t.example/x"))
        assert info.thumbnail is None and info.title == "T"


def test_thumbnail_request_is_size_limited_and_goes_through_the_safe_client():
    client = FakeClient(resp(200, body=JPEG))
    SourceService([StubSource("t.example", "https://t.example/i.jpg")], http_client=client).analyze(vurl("https://t.example/x"))
    method, url, _, max_body = client.calls[0]
    assert (method, url) == ("GET", "https://t.example/i.jpg") and 0 < max_body <= 2_000_000


def test_sniffing_ignores_server_claims():
    assert sniff_image_type(JPEG) == "image/jpeg" and sniff_image_type(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert sniff_image_type(b"GIF89a....") == "image/gif" and sniff_image_type(b"<svg") is None
