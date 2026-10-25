import json
import os
import sys
import threading
import time

import pytest

from backend.app.core.errors import AppError, ErrorCode, OperationCancelled
from backend.app.models.media import MediaFormat
from backend.app.services.http_client import TransferProgress
from backend.app.services.sources.base import DownloadContext
from backend.app.services.sources.ytdlp import (
    YtDlpSource,
    find_part_file,
    parse_progress_line,
)
from backend.app.utils.urls import validate_url

FAKE = r'''
import json, os, sys, time
argv = sys.argv[1:]
out = argv[argv.index("-o") + 1].replace("%%", "%").replace("%(ext)s", "mp4")
url = argv[-1]
open(out + ".argv.json", "w").write(json.dumps(argv))
mode = url.rsplit("/", 1)[-1]
if mode == "ok":
    for i in range(1, 4):
        print(f"PMPROG {i*1000} 3000 NA {500.5*i} {3-i}", flush=True)
    open(out, "wb").write(b"x" * 3000)
elif mode == "noisy":
    print("[download] some other line"); print("PMPROG junk"); print("PMPROG 1 2 3"); print("PMPROG -5 NA NA NA NA", flush=True)
    open(out, "wb").write(b"x")
elif mode == "fail404":
    print("ERROR: Unable to download webpage: HTTP Error 404: Not Found", file=sys.stderr); sys.exit(1)
elif mode == "failgeneric":
    print("ERROR: something odd happened", file=sys.stderr); sys.exit(1)
elif mode == "nofile":
    pass
elif mode == "toobig":
    print("[download] File is larger than max-filesize (5 bytes > 3 bytes). Aborting.")
elif mode == "partial":
    open(out + ".part", "wb").write(b"zz"); open(out + ".ytdl", "wb").write(b"zz")
elif mode == "hang":
    print("PMPROG 10 100 NA 10 9", flush=True); print(os.getpid(), flush=True); time.sleep(60)
'''


@pytest.fixture
def fake_cmd(tmp_path):
    script = tmp_path / "fake_ytdlp.py"
    script.write_text(FAKE)
    return [sys.executable, str(script)]


def source(fake_cmd):
    return YtDlpSource(frozenset({"archive.org"}), base_command=fake_cmd)


FMT = MediaFormat("mp4-720", "video", "mp4", "720p", True, 3000, False, "x")


def ctx(cancel=None, updates=None, **kw):
    return DownloadContext(
        cancel=cancel or threading.Event(),
        on_progress=(updates.append if updates is not None else (lambda p: None)),
        max_bytes=kw.pop("max_bytes", 10**9),
        **kw,
    )


def url(mode):
    return validate_url(f"https://archive.org/details/{mode}", resolve=False)


# ---------------------------------------------------------- progress parsing


def test_progress_line_parsing():
    p = parse_progress_line("PMPROG 1500 3000 NA 750.5 2")
    assert p == TransferProgress(1500, 3000, 750.5, 2.0)
    assert parse_progress_line("PMPROG 10 NA 5000 NA NA") == TransferProgress(10, 5000, None, None)  # estimate used
    assert parse_progress_line("PMPROG 10 NA NA NA NA") == TransferProgress(10, None, None, None)


@pytest.mark.parametrize("line", ["", "hello", "PMPROG", "PMPROG 1 2 3", "PMPROG x 1 2 3 4", "PMPROG -5 NA NA NA NA",
                                   "PMPROG nan 1 2 3 4", "[download] 50%", "xPMPROG 1 2 3 4 5"])
def test_junk_progress_lines_are_ignored(line):
    assert parse_progress_line(line) is None


def test_part_file_finder_ignores_partials_other_parts_symlinks_and_odd_names(tmp_path):
    (tmp_path / "part0.mp4.part").write_text("x")
    (tmp_path / "part0.ytdl").write_text("x")
    (tmp_path / "part0.part").write_text("x")
    (tmp_path / "part1.mp4").write_text("x")
    (tmp_path / "evil;rm.mp4").write_text("x")
    (tmp_path / "part0.mp4.exe").write_text("x")
    assert find_part_file(tmp_path, 0) is None
    (tmp_path / "part0.webm").write_text("done")
    assert find_part_file(tmp_path, 0).name == "part0.webm"
    assert find_part_file(tmp_path, 1).name == "part1.mp4"


# ---------------------------------------------------------- command line


def test_download_command_is_hardened_and_uses_only_validated_values(tmp_path):
    src = YtDlpSource(frozenset({"archive.org"}))
    cmd = src.build_download_command("https://archive.org/details/x?a=$(whoami)", "mp4-720", tmp_path, 1,
                                      ctx(max_bytes=12345, ffmpeg_location="/usr/bin/ffmpeg"))
    assert isinstance(cmd, list) and cmd[-2:] == ["--", "https://archive.org/details/x?a=$(whoami)"]
    for flag in ("--ignore-config", "--no-plugin-dirs", "--no-exec", "--no-playlist", "--newline"):
        assert flag in cmd
    assert cmd[cmd.index("-f") + 1] == "mp4-720" and cmd[cmd.index("--max-filesize") + 1] == "12345"
    assert cmd[cmd.index("--ffmpeg-location") + 1] == "/usr/bin/ffmpeg"
    assert cmd[cmd.index("-o") + 1] == str(tmp_path / "part1").replace("%", "%%") + ".%(ext)s"
    assert not any(a.startswith("--cookies") or a in ("--netrc", "--username", "--password") for a in cmd)


@pytest.mark.parametrize("bad", ["--exec=calc", "-o /etc/x", "a b", "a;b", "$(x)", "", "../x", "a/b", "x" * 101, "-x"])
def test_unsafe_format_ids_never_reach_the_command_line(tmp_path, bad):
    with pytest.raises(AppError) as exc:
        YtDlpSource(frozenset({"archive.org"})).build_download_command("https://archive.org/x", bad, tmp_path, 0, ctx())
    assert exc.value.code is ErrorCode.FORMAT_NOT_AVAILABLE


def test_percent_signs_in_our_own_paths_are_escaped(tmp_path):
    d = tmp_path / "100%done"
    cmd = YtDlpSource(frozenset({"archive.org"})).build_download_command("https://archive.org/x", "a", d, 0, ctx())
    assert "100%%done" in cmd[cmd.index("-o") + 1]


# -------------------------------------------------------- real subprocess runs


def test_successful_download_reports_progress_and_writes_the_expected_file(fake_cmd, tmp_path):
    updates = []
    path = source(fake_cmd).download(url("ok"), FMT, tmp_path, 0, ctx(updates=updates))
    assert path == tmp_path / "part0.mp4" and path.stat().st_size == 3000
    assert [u.downloaded for u in updates] == [1000, 2000, 3000] and updates[-1].total == 3000
    assert updates[0].speed == pytest.approx(500.5) and updates[0].eta == 2


def test_the_real_command_line_reached_the_program_intact(fake_cmd, tmp_path):
    d = tmp_path / "with%percent"
    d.mkdir()
    source(fake_cmd).download(url("ok"), FMT, d, 0, ctx(max_bytes=777))
    argv = json.loads((d / "part0.mp4.argv.json").read_text())
    assert argv[-2:] == ["--", "https://archive.org/details/ok"] and "777" in argv
    assert (d / "part0.mp4").exists(), "a literal % in our directory must survive yt-dlp's template parsing"


def test_noise_in_the_output_does_not_break_the_download(fake_cmd, tmp_path):
    updates = []
    source(fake_cmd).download(url("noisy"), FMT, tmp_path, 0, ctx(updates=updates))
    assert updates == []


def test_failures_map_to_categories(fake_cmd, tmp_path):
    with pytest.raises(AppError) as exc:
        source(fake_cmd).download(url("fail404"), FMT, tmp_path, 0, ctx())
    assert exc.value.code is ErrorCode.MEDIA_NOT_AVAILABLE
    with pytest.raises(AppError) as exc:
        source(fake_cmd).download(url("failgeneric"), FMT, tmp_path, 0, ctx())
    assert exc.value.code is ErrorCode.DOWNLOAD_FAILED and "odd" not in exc.value.message


def test_clean_exit_without_a_file_is_a_failure(fake_cmd, tmp_path):
    with pytest.raises(AppError) as exc:
        source(fake_cmd).download(url("nofile"), FMT, tmp_path, 0, ctx())
    assert exc.value.reason == "no_output"


def test_max_filesize_skip_is_reported_as_too_large(fake_cmd, tmp_path):
    with pytest.raises(AppError) as exc:
        source(fake_cmd).download(url("toobig"), FMT, tmp_path, 0, ctx())
    assert exc.value.reason == "too_large"


def test_leftover_partial_files_do_not_count_as_a_finished_download(fake_cmd, tmp_path):
    with pytest.raises(AppError) as exc:
        source(fake_cmd).download(url("partial"), FMT, tmp_path, 0, ctx())
    assert exc.value.reason == "no_output"


def test_cancel_kills_the_extractor_process(fake_cmd, tmp_path):
    cancel, pids = threading.Event(), []
    started = time.time()
    s = source(fake_cmd)

    def on_progress(p):
        cancel.set()

    with pytest.raises(OperationCancelled):
        s.download(url("hang"), FMT, tmp_path, 0, DownloadContext(cancel=cancel, on_progress=on_progress, max_bytes=10**9))
    assert time.time() - started < 10


def test_overall_timeout_stops_the_extractor(fake_cmd, tmp_path):
    with pytest.raises(AppError) as exc:
        source(fake_cmd).download(url("hang"), FMT, tmp_path, 0, ctx(timeout=0.8))
    assert exc.value.code is ErrorCode.TIMEOUT and exc.value.reason == "process_timeout"
