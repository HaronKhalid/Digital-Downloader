import os
import sys
import threading
import time

import pytest

from backend.app.services.process_utils import (
    ProcessCancelled,
    ProcessTimeout,
    run_controlled,
    windows_kill_args,
)

ENV = {"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}
PY = sys.executable


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie still "exists"; treat it as dead
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(") ")[-1].split()[0] != "Z"
    except OSError:
        return True


def wait_dead(pid, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_streams_lines_and_returns_exit_code_and_tail():
    seen = []
    r = run_controlled([PY, "-c", "import sys; print('a'); print('b', file=sys.stderr); sys.exit(3)"], env=ENV, on_line=seen.append)
    assert r.returncode == 3 and sorted(seen) == ["a", "b"] and set(r.tail) == {"a", "b"}


def test_tail_is_bounded():
    r = run_controlled([PY, "-c", "for i in range(500): print(i)"], env=ENV, tail_lines=5)
    assert r.tail == ("495", "496", "497", "498", "499")


def test_very_long_lines_are_truncated():
    r = run_controlled([PY, "-c", "print('x' * 100000)"], env=ENV)
    assert len(r.tail[0]) <= 2000


def test_environment_is_exactly_what_the_caller_provides(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    r = run_controlled([PY, "-c", "import os; print(os.environ.get('SECRET_TOKEN'), os.environ.get('ONLY_THIS'))"], env={**ENV, "ONLY_THIS": "yes"})
    assert r.tail == ("None yes",)


def test_shell_metacharacters_in_arguments_are_inert(tmp_path):
    marker = tmp_path / "pwned"
    run_controlled([PY, "-c", "import sys; print(sys.argv[1])", f"; touch {marker}; $(touch {marker}) `touch {marker}`"], env=ENV)
    assert not marker.exists()


def test_missing_program_raises_oserror():
    with pytest.raises(OSError):
        run_controlled(["definitely-not-a-real-program-xyz"], env=ENV)


def test_timeout_kills_the_process():
    pids = []
    with pytest.raises(ProcessTimeout):
        run_controlled([PY, "-c", "import os,time; print(os.getpid(), flush=True); time.sleep(60)"], env=ENV, timeout=0.6, on_line=lambda l: pids.append(int(l)))
    assert wait_dead(pids[0])


def test_cancel_kills_process_and_grandchildren():
    child = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid, flush=True); time.sleep(60)"
    cancel, pids = threading.Event(), []

    def on_line(line):
        pids.append(int(line))
        cancel.set()

    started = time.time()
    with pytest.raises(ProcessCancelled):
        run_controlled([PY, "-c", child], env=ENV, cancel=cancel, on_line=on_line)
    assert time.time() - started < 10
    assert wait_dead(pids[0]), "grandchild process was orphaned"


def test_cancel_before_start_still_cleans_up():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ProcessCancelled):
        run_controlled([PY, "-c", "import time; time.sleep(60)"], env=ENV, cancel=cancel)


def test_callback_exception_stops_the_process():
    pids = []

    def boom(line):
        pids.append(int(line))
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError):
        run_controlled([PY, "-c", "import os,time; print(os.getpid(), flush=True); time.sleep(60)"], env=ENV, on_line=boom)
    assert wait_dead(pids[0])


def test_windows_kill_command_is_an_argument_list_covering_children():
    assert windows_kill_args(1234) == ["taskkill", "/PID", "1234", "/T", "/F"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal semantics")
def test_processes_that_ignore_sigterm_are_still_killed_including_their_children():
    stubborn = (
        "import signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'\n"
        "p = subprocess.Popen([sys.executable, '-c', child])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    cancel, pids = threading.Event(), []

    def on_line(line):
        pids.append(int(line))
        cancel.set()

    started = time.time()
    with pytest.raises(ProcessCancelled):
        run_controlled([PY, "-c", stubborn], env=ENV, cancel=cancel, on_line=on_line)
    assert time.time() - started < 15
    assert wait_dead(pids[0]), "a SIGTERM-ignoring grandchild survived"
