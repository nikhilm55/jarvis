"""Tests for jarvis.orchestrator.lifeline.parent_death_preexec."""

import contextlib
import os
import signal
import subprocess
import sys
import time

import pytest

from jarvis.orchestrator.lifeline import parent_death_preexec


class _Exited(Exception):
    """Raised by the fake os._exit to capture the exit code."""

    def __init__(self, code: int) -> None:
        super().__init__(f"exited with code {code}")
        self.code = code


class FakeLibc:
    """Records prctl calls and returns a configurable status."""

    def __init__(self, status: int = 0) -> None:
        self.status = status
        self.calls: list[tuple[int, int, int, int, int]] = []

    def prctl(self, option: int, arg2: int, arg3: int, arg4: int, arg5: int) -> int:
        self.calls.append((option, arg2, arg3, arg4, arg5))
        return self.status


_LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux", reason="PR_SET_PDEATHSIG is Linux-only (M1)"
)


@_LINUX_ONLY
def test_should_record_prctl_sigterm_when_parent_pid_is_real_parent() -> None:
    libc = FakeLibc(status=0)
    preexec = parent_death_preexec(libc, parent_pid=os.getppid())
    assert preexec is not None
    preexec()
    assert len(libc.calls) == 1
    assert libc.calls[0] == (1, signal.SIGTERM, 0, 0, 0)


def _fake_exit(code: int) -> None:
    raise _Exited(code)


@_LINUX_ONLY
def test_should_exit_when_parent_pid_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    libc = FakeLibc(status=0)
    preexec = parent_death_preexec(libc, parent_pid=os.getpid() + 10_000_000)
    assert preexec is not None

    monkeypatch.setattr("os._exit", _fake_exit)
    with pytest.raises(_Exited) as exc_info:
        preexec()
    assert exc_info.value.code == 1


@_LINUX_ONLY
def test_should_exit_when_prctl_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    libc = FakeLibc(status=-1)
    preexec = parent_death_preexec(libc, parent_pid=os.getppid())
    assert preexec is not None

    monkeypatch.setattr("os._exit", _fake_exit)
    with pytest.raises(_Exited) as exc_info:
        preexec()
    assert exc_info.value.code == 1


def test_should_return_none_when_platform_is_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.lifeline.sys.platform", "win32")
    result = parent_death_preexec(FakeLibc())
    assert result is None


@pytest.mark.skipif(sys.platform != "linux", reason="PR_SET_PDEATHSIG is Linux-only")
def test_should_kill_child_when_parent_dies() -> None:
    parent_script = (
        "import subprocess, sys, time\n"
        "from jarvis.orchestrator.lifeline import parent_death_preexec\n"
        "child = subprocess.Popen(['sleep', '30'], preexec_fn=parent_death_preexec())\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )

    parent = subprocess.Popen(
        [sys.executable, "-c", parent_script],
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    assert parent.stdout is not None
    pid_line = parent.stdout.readline().strip()
    child_pid = int(pid_line)

    try:
        parent.kill()
        parent.wait()

        deadline = time.monotonic() + 2.0
        gone = False
        while time.monotonic() < deadline:
            if _gone(child_pid):
                gone = True
                break
            time.sleep(0.02)

        assert gone, f"child {child_pid} was not reaped within 2 s"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child_pid, signal.SIGKILL)
        if parent.poll() is None:
            parent.kill()
            parent.wait()


def _gone(pid: int) -> bool:
    stat_path = f"/proc/{pid}/stat"
    try:
        with open(stat_path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return True
    close_paren = content.rfind(")")
    if close_paren == -1:
        return False
    state_char = content[close_paren + 2 : close_paren + 3]
    return state_char == "Z"
