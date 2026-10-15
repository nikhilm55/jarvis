"""The brain child's stderr lands in a log file (FRS FR-LOG-05), never in a pipe or the void."""

import asyncio
import os
import stat
import sys
from pathlib import Path

import pytest

from jarvis.brain import process as process_module
from jarvis.brain.failures import process_exit_response
from jarvis.brain.launch import LaunchSpec
from jarvis.brain.process import ClaudeProcess
from jarvis.brain.stderr_log import stderr_log_path

_NOISY = "import sys; sys.stderr.write('Error: not logged in\\n'); sys.stderr.flush()"


async def run_to_exit(tmp_path: Path) -> None:
    proc = await ClaudeProcess.spawn(
        LaunchSpec([sys.executable, "-c", _NOISY], tmp_path, dict(os.environ)), lambda _event: None
    )
    async with asyncio.timeout(10):
        while proc.alive:
            await asyncio.sleep(0.02)
    await proc.kill()


def test_should_write_the_childs_stderr_to_the_log_when_it_prints_an_error(tmp_path: Path) -> None:
    asyncio.run(run_to_exit(tmp_path))

    assert "Error: not logged in" in stderr_log_path().read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_should_keep_the_stderr_log_private_when_it_is_created(tmp_path: Path) -> None:
    asyncio.run(run_to_exit(tmp_path))

    assert stat.S_IMODE(stderr_log_path().stat().st_mode) == 0o600


def test_should_still_start_the_brain_when_the_stderr_log_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> int:
        raise PermissionError("read-only disk")

    monkeypatch.setattr(process_module, "open_stderr_log", broken)

    asyncio.run(run_to_exit(tmp_path))

    assert not stderr_log_path().exists()


def test_should_point_at_the_stderr_log_when_the_brain_process_stopped() -> None:
    response = process_exit_response()

    assert response.error is not None
    assert response.error.code == "BRAIN_UNAVAILABLE"
    assert str(stderr_log_path()) in " ".join(response.error.remedy)
