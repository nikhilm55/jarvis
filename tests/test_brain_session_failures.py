"""ClaudeCodeBrain failure modes: timeouts, dead processes, login/quota errors, lifecycle."""

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from jarvis.brain.failures import BrainUnavailable
from jarvis.brain.process import ClaudeProcess
from tests.brain_fakes import FakeClaude, process_gone, wait_until
from tests.brain_rig import Rig, running_brain

OK: list[dict[str, Any]] = [
    {"call": "respond", "args": {"status": "success", "spoken": "Done."}},
    {"result": "Done."},
]


def drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    turns: list[list[dict[str, Any]]],
    scenario: Callable[[Rig, FakeClaude], Awaitable[None]],
    *,
    child: bool = False,
    **brain: Any,
) -> None:
    """Run `scenario` against a started rig whose fake claude replays `turns`."""
    fake = FakeClaude(tmp_path, monkeypatch, turns, child=child)

    async def main() -> None:
        async with running_brain(fake, **brain) as rig:
            await scenario(rig, fake)

    asyncio.run(main())


def test_should_time_out_and_restart_when_a_turn_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        await rig.brain.start()
        pid1 = rig.brain.pid
        assert pid1 is not None
        # The fake counts the turns it has read. A cold start slower than the 1 s budget (its
        # imports, on a loaded host) would kill it before it read t1, so the restarted one would
        # replay the hang for t2. Wait for it to be up so the budget times only the hang.
        await wait_until(lambda: len(fake.spawns()) == 1, timeout_s=60)
        first = await rig.turn()
        assert first.error is not None
        assert first.error.code == "TIMEOUT"
        assert process_gone(pid1)
        # The 1 s budget only detects the hang. The restarted turn also pays for a cold claude
        # start (~1 s on a Windows runner, so a 1 s clock timed it out ~10% of the time).
        rig.settings.turn_timeout_s = 60
        assert (await rig.turn(turn_id="t2")).status == "success"
        assert len(fake.spawns()) == 2
        assert rig.brain.pid != pid1

    drive(tmp_path, monkeypatch, [[{"hang": True}], OK], scenario, turn_timeout_s=1)


def test_should_report_brain_unavailable_when_the_process_dies_mid_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        first = await rig.turn()
        assert first.error is not None
        assert first.error.code == "BRAIN_UNAVAILABLE"
        assert "stopped" in first.error.why
        assert (await rig.turn(turn_id="t2")).status == "success"
        assert len(fake.spawns()) == 2

    drive(tmp_path, monkeypatch, [[{"exit": 3}], OK], scenario)


def test_should_report_brain_unavailable_when_the_binary_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        response = await rig.turn()
        assert response.error is not None
        assert response.error.code == "BRAIN_UNAVAILABLE"
        with pytest.raises(BrainUnavailable):
            await rig.brain.start()

    drive(tmp_path, monkeypatch, [], scenario, claude_bin="/nonexistent/claude")


def test_should_ask_for_a_login_and_keep_the_session_when_claude_is_logged_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged_out: list[dict[str, Any]] = [
        {"error": "authentication_failed", "text": "Not logged in"},
        {"result": "Not logged in · Please run /login", "is_error": True},
    ]

    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        first = await rig.turn()
        assert first.error is not None
        assert first.error.code == "BRAIN_UNAVAILABLE"
        assert "logged in" in first.error.why
        assert first.error.remedy
        assert (await rig.turn(turn_id="t2")).status == "success"
        assert len(fake.spawns()) == 1

    drive(tmp_path, monkeypatch, [logged_out, OK], scenario)


def test_should_name_the_limit_when_the_usage_limit_is_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limited: list[dict[str, Any]] = [
        {"error": "rate_limit", "text": "limit"},
        {"result": "You've hit your usage limit", "is_error": True},
    ]

    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        response = await rig.turn()
        assert response.error is not None
        assert (response.error.code, "limit" in response.error.why) == ("BRAIN_UNAVAILABLE", True)

    drive(tmp_path, monkeypatch, [limited], scenario)


def test_should_report_mcp_unavailable_and_restart_when_the_tool_server_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        first = await rig.turn()
        assert first.error is not None
        assert first.error.code == "MCP_UNAVAILABLE"
        assert (await rig.turn(turn_id="t2")).status == "success"
        assert len(fake.spawns()) == 2

    drive(tmp_path, monkeypatch, [[{"init": "failed"}, {"result": "x"}], OK], scenario)


def test_should_start_a_fresh_warm_process_when_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        await rig.brain.start()
        pid1 = rig.brain.pid
        assert pid1 is not None
        await rig.brain.reset()
        assert rig.brain.pid not in (None, pid1)
        assert process_gone(pid1)
        assert (await rig.turn()).status == "success"

    drive(tmp_path, monkeypatch, [OK], scenario)


@pytest.mark.skipif(
    sys.platform != "linux",
    reason=(
        "on Windows, kill() ends only the .cmd shim; the brain process survives "
        "(needs a Job Object, Windows milestone)"
    ),
)
def test_should_kill_the_process_group_when_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        await rig.turn()
        child, pid = fake.child_pid(), rig.brain.pid
        assert child is not None
        assert pid is not None
        await rig.brain.close()
        assert process_gone(pid)
        await wait_until(lambda: process_gone(child))
        response = await rig.turn(turn_id="t2")
        assert response.error is not None
        assert response.error.code == "BRAIN_UNAVAILABLE"

    drive(tmp_path, monkeypatch, [OK], scenario, child=True)


def test_should_end_the_running_turn_when_closed_mid_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        task = asyncio.create_task(rig.turn())
        try:
            await wait_until(lambda: any("user" in r for r in fake.records()))
            await rig.brain.close()
            response = await asyncio.wait_for(task, 10)
            assert response.error is not None
            assert response.error.code == "BRAIN_UNAVAILABLE"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    drive(tmp_path, monkeypatch, [[{"hang": True}]], scenario)


def test_should_kill_the_session_and_restart_when_a_turn_is_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        await rig.brain.start()
        pid1 = rig.brain.pid
        assert pid1 is not None
        task = asyncio.create_task(rig.turn())
        try:
            await wait_until(lambda: any("user" in r for r in fake.records()))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert process_gone(pid1)
            assert (await rig.turn(turn_id="t2")).status == "success"
            assert len(fake.spawns()) == 2
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    drive(tmp_path, monkeypatch, [[{"hang": True}], OK], scenario)


def test_should_drop_the_session_and_report_internal_when_a_turn_hits_a_bug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(self: ClaudeProcess, text: str) -> None:
        raise RuntimeError("boom")

    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        await rig.brain.start()
        pid1 = rig.brain.pid
        assert pid1 is not None
        monkeypatch.setattr(ClaudeProcess, "send", explode)
        response = await rig.turn()
        assert response.error is not None
        assert response.error.code == "INTERNAL"
        assert process_gone(pid1)

    drive(tmp_path, monkeypatch, [OK], scenario)


def test_should_not_leave_a_process_behind_when_closed_during_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[ClaudeProcess] = []
    real_spawn: Any = ClaudeProcess.spawn.__func__  # type: ignore[attr-defined]

    async def scenario(rig: Rig, fake: FakeClaude) -> None:
        async def spawn_then_close(cls: type[ClaudeProcess], spec: Any, sink: Any) -> ClaudeProcess:
            proc: ClaudeProcess = await real_spawn(cls, spec, sink)
            spawned.append(proc)
            await rig.brain.close()  # arrives while the brain is still starting this process
            return proc

        monkeypatch.setattr(ClaudeProcess, "spawn", classmethod(spawn_then_close))
        response = await rig.turn()
        assert response.error is not None
        assert response.error.code == "BRAIN_UNAVAILABLE"
        assert process_gone(spawned[0].pid)

    drive(tmp_path, monkeypatch, [OK], scenario)
