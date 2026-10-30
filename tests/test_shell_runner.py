"""The shell runner: process group, capped streams, timeout and the kill switch (R84, task 8).

These run a real bash; on Windows the runner uses cmd.exe, so only the POSIX paths are tested.
They are unit tests: every command is innocent (`echo`, `sleep`, `seq`) and nothing touches
the user's data — no consent, no gate, no real machine changes.
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

from jarvis.killswitch import KillSwitch
from jarvis.shell.runner import DEFAULT_TIMEOUT_S, MAX_CAPTURE, ShellRunner

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="shell.exe - the runner spawns bash, a POSIX process group (R84)",
)


def runner() -> ShellRunner:
    return ShellRunner()


def test_should_capture_stdout_and_the_exit_code() -> None:
    out = runner().run("echo hi")
    assert out == {
        "stdout": "hi\n",
        "stderr": "",
        "exit": 0,
        "timed_out": False,
        "truncated": False,
    }
    assert DEFAULT_TIMEOUT_S == 60.0


def test_should_capture_stderr_and_a_non_zero_exit() -> None:
    out = runner().run("echo bad 1>&2; exit 3")
    assert out["stderr"] == "bad\n"
    assert out["stdout"] == ""
    assert out["exit"] == 3


def test_should_cap_each_stream_at_64_kib_and_report_truncation() -> None:
    out = runner().run("seq 1 200000")
    assert len(out["stdout"]) == MAX_CAPTURE
    assert out["truncated"] is True
    assert out["exit"] == 0


def test_should_run_in_the_requested_folder() -> None:
    out = runner().run("pwd", cwd=str(Path(__file__).resolve().parent))
    assert out["stdout"].strip() == str(Path(__file__).resolve().parent)


def test_should_raise_when_the_cwd_does_not_exist() -> None:
    with pytest.raises(FileNotFoundError):
        runner().run("true", cwd="~/does-not-exist-xyz")


def test_should_time_out_and_kill_the_group() -> None:
    started = time.monotonic()
    out = runner().run("sleep 30", timeout_s=1)
    elapsed = time.monotonic() - started
    assert out["timed_out"] is True
    assert out["exit"] == -9  # SIGKILL
    assert elapsed < 5


def test_should_stop_the_group_when_the_kill_switch_fires() -> None:
    notes: list[str] = []

    async def stop() -> None:
        notes.append("stopped")

    killswitch = KillSwitch(stop)
    shell = runner()
    shell.bind(killswitch.register_process)
    result: dict[str, object] = {}

    def work() -> None:
        result["run"] = shell.run("sleep 30; echo late", timeout_s=60)

    thread = threading.Thread(target=work)
    thread.start()
    time.sleep(0.3)
    started = time.monotonic()
    threading.Thread(target=lambda: asyncio.run(killswitch.trigger("hotkey"))).start()
    thread.join(timeout=2)
    elapsed = time.monotonic() - started
    assert not thread.is_alive(), "the run returned after the kill switch fired"
    run = result["run"]
    assert isinstance(run, dict)
    assert run["exit"] == -9
    assert run["timed_out"] is False
    assert elapsed < 2  # the group died within ~300 ms (R84 (c)); the wait is the residue
