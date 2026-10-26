import pytest
from core.models.media import MediaFormat
from core.formats.selector import sort_formats, find_format, find_compatible_audio


def test_sort_formats():
    v1080 = MediaFormat(id="v1", type="video", container="mp4", resolution="1080p", has_audio=True)
    v720 = MediaFormat(id="v2", type="video", container="mp4", resolution="720p", has_audio=True)
    v480 = MediaFormat(id="v3", type="video", container="mp4", resolution="480p", has_audio=True)
    audio = MediaFormat(id="a1", type="audio", container="m4a", resolution=None, has_audio=True)

    sorted_fmts = sort_formats([v480, audio, v1080, v720])
    ids = [f.id for f in sorted_fmts]
    assert ids == ["v1", "v2", "v3", "a1"]


def test_find_format():
    fmts = [
        MediaFormat(id="v1", type="video", container="mp4", resolution="1080p", has_audio=True),
        MediaFormat(id="a1", type="audio", container="m4a", resolution=None, has_audio=True),
    ]
    assert find_format(fmts, "v1") is fmts[0]
    assert find_format(fmts, "a1") is fmts[1]
    assert find_format(fmts, "nonexistent") is None


def test_find_compatible_audio():
    a_m4a = MediaFormat(id="a_m4a", type="audio", container="m4a", resolution=None, has_audio=True)
    a_webm = MediaFormat(id="a_webm", type="audio", container="webm", resolution=None, has_audio=True)
    fmts = [a_m4a, a_webm]

    assert find_compatible_audio(fmts, "mp4") == a_m4a
    assert find_compatible_audio(fmts, "webm") == a_webm
