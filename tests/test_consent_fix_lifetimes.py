"""Regression tests for M2 task 3, part B: I3, M1 and M2 (session lifetimes)."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.consent.scope import Scope
from jarvis.consent.session import SESSION_MAX_S, SessionGrants
from jarvis.orchestrator.core import Orchestrator
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from tests.consent_rig import TEAMS_R, make_rig, says
from tests.core_rig import CoreRig
from tests.listener_rig import seg

TEAMS = Scope.parse(TEAMS_R)
MAIL = Scope.parse("email.outlook:read")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_should_expire_a_session_grant_when_the_clock_jumps_8h_and_1s() -> None:
    clock = Clock()
    grants = SessionGrants(clock)
    grants.grant(TEAMS, "session", "t1")
    assert grants.holds(TEAMS, "t1")
    clock.now += 3600
    assert grants.holds(TEAMS, "t1")  # an hour in: still held
    clock.now += SESSION_MAX_S - 3600 + 1  # a suspend carries the clock past 8 h in one step
    assert not grants.holds(TEAMS, "t1")


def test_should_end_every_grant_on_end_after_the_clock_ran() -> None:
    clock = Clock()
    grants = SessionGrants(clock)
    grants.grant(MAIL, "session", "t1")
    clock.now += SESSION_MAX_S + 1
    assert not grants.holds(MAIL, "t1")
    grants.grant(MAIL, "session", "t1")  # granted again, then the session ends
    assert grants.holds(MAIL, "t1")
    grants.end("brain_reset")
    assert not grants.holds(MAIL, "t1")


def test_should_read_clock_boottime_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform != "linux":
        pytest.skip("CLOCK_BOOTTIME exists on Linux only; elsewhere the wall clock is used")
    ids: list[int] = []
    now = [5000.0]

    def fake_gettime(clock_id: int) -> float:
        ids.append(clock_id)
        return now[0]

    monkeypatch.setattr(time, "clock_gettime", fake_gettime)
    grants = SessionGrants()
    grants.grant(TEAMS, "session", "t1")
    now[0] += SESSION_MAX_S + 1  # the machine slept: BOOTTIME kept counting
    assert not grants.holds(TEAMS, "t1")
    assert ids
    assert set(ids) == {time.CLOCK_BOOTTIME}


def test_should_refuse_a_once_grant_outside_a_turn() -> None:
    grants = SessionGrants()
    grants.grant(TEAMS, "once", "no-turn")
    assert not grants.holds(TEAMS, "no-turn")


def test_should_deny_a_once_answer_outside_a_turn_and_ask_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("once"))
    assert rig.require(TEAMS_R, turn="no-turn") == "denied"
    assert not rig.session.holds(TEAMS, "no-turn")
    assert rig.require(TEAMS_R, turn="no-turn") == "denied"
    assert len(rig.asker.asked) == 2  # nothing was held, so the second call asked again
    assert rig.require(TEAMS_R, turn="t1") == "granted"  # inside a turn, once still works


def test_should_deny_a_once_answer_under_the_idle_tool_trace_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("once"))
    ctx = ToolTrace(consent=rig.broker).turn_context()  # what a call between turns gets
    assert ctx.turn_id == "no-turn"
    assert asyncio.run(rig.broker.require((TEAMS_R,), "to read", ctx)) == "denied"
    assert not rig.session.holds(TEAMS, ctx.turn_id)


def test_should_end_session_grants_when_the_brain_reset_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        grants = SessionGrants()
        grants.grant(TEAMS, "session", "turn-1")
        assert grants.holds(TEAMS, "turn-1")
        timing = Timing(deaf_tail_s=0.0, inactivity_reset_s=0.05)
        rig = CoreRig(tmp_path, ["Jarvis, what's the plan?"], timing=timing)
        assert rig.brain is not None
        brain = rig.brain

        async def failing_reset() -> None:
            brain.reset_called.set()
            raise RuntimeError("the brain is gone")

        monkeypatch.setattr(brain, "reset", failing_reset)
        rig.parts.grants = grants
        rig.orchestrator = Orchestrator(
            Settings(),
            rig.parts,
            hud=rig._hud,
            activity=rig.orchestrator._activity,
            timing=timing,
        )
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await asyncio.wait_for(brain.reset_called.wait(), 5)
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        assert not grants.holds(TEAMS, "turn-1")

    asyncio.run(scenario())
