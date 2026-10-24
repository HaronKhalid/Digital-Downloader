import re
import unicodedata
from pathlib import Path

import pytest

from backend.app.services.file_service import (
    PathSafetyError,
    is_within,
    job_temp_dir,
    remove_job_dir,
    safe_join,
    unique_destination,
    validate_output_directory,
)
from backend.app.utils.filenames import (
    WINDOWS_RESERVED,
    build_output_filename,
    sanitize_filename,
    sanitize_stem,
)

FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def assert_single_safe_component(name: str):
    assert name and not FORBIDDEN.search(name)
    # Windows ANSI best-fit conversion can turn look-alikes (e.g. full-width "／") into
    # real separators, so the *normalized* form must be safe too.
    assert unicodedata.normalize("NFKC", name) == name
    assert not FORBIDDEN.search(unicodedata.normalize("NFKC", name))
    assert ".." not in name
    assert not name.startswith((".", "-", " "))
    assert not name.endswith((".", " "))
    assert name.split(".", 1)[0].upper() not in WINDOWS_RESERVED
    assert Path(name).name == name


# ------------------------------------------------------------ filenames

HOSTILE_TITLES = [
    "../../important.txt",
    "..\\..\\file",
    "../../../../etc/passwd",
    "C:\\Windows\\System32\\cmd.exe",
    "/etc/passwd",
    "\\\\server\\share\\x",
    "..%2f..%2fx",
    "a／b＼c",  # full-width slashes
    "evil\u202egnp.exe",  # right-to-left override
    "a\x00b\nc\td",
    "CON",
    "nul.txt",
    "COM1",
    "lpt9.mp4",
    "aux.tar.gz",
    "video. . .",
    "   ",
    "...",
    "-rf",
    "--output=/tmp/x",
    "; rm -rf /",
    "$(whoami)",
    "`id`",
    "| calc",
    "&& del *.*",
    '"; shutdown /s /t 0; "',
    "a" * 500,
]


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_sanitize_stem_always_returns_one_safe_component(title):
    assert_single_safe_component(sanitize_stem(title))


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_sanitize_filename_always_returns_one_safe_component(title):
    assert_single_safe_component(sanitize_filename(title))


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_built_output_filename_is_safe_and_has_allowed_extension(title):
    name = build_output_filename(title, "mp4")
    assert name.endswith(".mp4")
    assert_single_safe_component(name.removesuffix(".mp4"))


def test_traversal_title_does_not_survive():
    assert sanitize_stem("../../important.txt") == "important.txt"


def test_reserved_names_are_neutralised():
    assert sanitize_stem("CON") == "_CON"
    assert sanitize_filename("nul.txt") == "_nul.txt"


def test_length_is_capped_and_extension_kept():
    assert len(sanitize_stem("a" * 500)) <= 121
    assert sanitize_filename("b" * 500 + ".mp4").endswith(".mp4")
    assert len(sanitize_filename("b" * 500 + ".mp4")) <= 121


def test_empty_and_none_fall_back_to_default():
    assert sanitize_stem(None) == "media"
    assert sanitize_stem("///") == "media"


def test_unicode_titles_are_preserved():
    assert sanitize_stem("日本語のタイトル") == "日本語のタイトル"


@pytest.mark.parametrize("ext", ["exe", "bat", "ps1", "../mp4", "mp4/", "", "html"])
def test_disallowed_extensions_rejected(ext):
    with pytest.raises(ValueError):
        build_output_filename("title", ext)


@pytest.mark.parametrize("ext", ["MP4", ".mkv", "mp3"])
def test_allowed_extensions_normalized(ext):
    assert build_output_filename("t", ext).rsplit(".", 1)[1] in {"mp4", "mkv", "mp3"}


# ---------------------------------------------------------------- paths


@pytest.mark.parametrize(
    "part",
    ["../../file", "..\\..\\file", "a/../../b", "a\\..\\..\\b", "..", "/etc/passwd",
     "C:\\Windows\\system32", "C:/Windows", "\\\\server\\share", "", "a\x00b"],
)
def test_safe_join_rejects_escapes(tmp_path, part):
    with pytest.raises(PathSafetyError):
        safe_join(tmp_path, part)


def test_safe_join_accepts_plain_names(tmp_path):
    result = safe_join(tmp_path, "sub", "file.mp4")
    assert is_within(tmp_path, result) and result.name == "file.mp4"


def test_safe_join_refuses_base_itself(tmp_path):
    with pytest.raises(PathSafetyError):
        safe_join(tmp_path, ".")


def test_safe_join_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    base = tmp_path / "base"
    base.mkdir()
    try:
        (base / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this platform")
    with pytest.raises(PathSafetyError):
        safe_join(base, "link", "secret.txt")


def test_job_dirs_are_isolated(tmp_path):
    a = job_temp_dir(tmp_path, "3f2b8c1e-5d4a-4b6f-9a1c-0e7d2f4b8a91")
    b = job_temp_dir(tmp_path, "7a9e4d20-1c3b-4f58-8e6a-5b2d9c0f1e34")
    assert a != b and not is_within(a, b) and not is_within(b, a)
    assert is_within(tmp_path, a) and is_within(tmp_path, b)


@pytest.mark.parametrize("bad", ["../x", "not-a-uuid", "", "..", "3f2b8c1e-5d4a-4b6f-9a1c-0e7d2f4b8a91/../x",
                                 "3F2B8C1E-5D4A-4B6F-9A1C-0E7D2F4B8A91", "{3f2b8c1e-5d4a-4b6f-9a1c-0e7d2f4b8a91}"])
def test_job_temp_dir_requires_canonical_uuid(tmp_path, bad):
    with pytest.raises(PathSafetyError):
        job_temp_dir(tmp_path, bad)


def test_remove_job_dir_deletes_only_inside_temp_root(tmp_path):
    temp = tmp_path / "temp"
    job = job_temp_dir(temp, "3f2b8c1e-5d4a-4b6f-9a1c-0e7d2f4b8a91")
    job.mkdir(parents=True)
    (job / "part.tmp").write_text("x")
    remove_job_dir(temp, job)
    assert not job.exists()

    victim = tmp_path / "important"
    victim.mkdir()
    with pytest.raises(PathSafetyError):
        remove_job_dir(temp, victim)
    with pytest.raises(PathSafetyError):
        remove_job_dir(temp, temp)
    assert victim.exists()


def test_output_directory_validation(tmp_path):
    assert validate_output_directory(tmp_path / "PersonalMedia") == (tmp_path / "PersonalMedia").resolve()
    with pytest.raises(PathSafetyError):
        validate_output_directory("relative/dir")
    with pytest.raises(PathSafetyError):
        validate_output_directory(Path(tmp_path.anchor))
    with pytest.raises(PathSafetyError):
        validate_output_directory(Path.home())


def test_unique_destination_never_overwrites(tmp_path):
    (tmp_path / "clip.mp4").write_text("a")
    (tmp_path / "clip (1).mp4").write_text("b")
    assert unique_destination(tmp_path, "clip.mp4").name == "clip (2).mp4"
    assert unique_destination(tmp_path, "fresh.mp4").name == "fresh.mp4"


# ------------------------------------------- command-injection guardrails

APP_DIR = Path(__file__).resolve().parents[1] / "app"
BANNED_PATTERNS = [r"shell\s*=\s*True", r"os\.system\(", r"os\.popen\(", r"\bcommands\.getoutput", r"create_subprocess_shell"]


def test_no_shell_execution_anywhere_in_backend():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in BANNED_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(APP_DIR)}: {pattern}")
    assert not offenders, offenders


def test_no_unsafe_html_insertion_in_frontend():
    js_dir = APP_DIR.parents[1] / "frontend" / "js"
    banned = re.compile(r"\.innerHTML\s*=|insertAdjacentHTML|document\.write|\beval\(")
    offenders = [p.name for p in js_dir.glob("*.js") if banned.search(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders
