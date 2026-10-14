"""Tests for jarvis.orchestrator.turns: no brain, earcons, cancellation and failures."""

import asyncio
from pathlib import Path

import pytest

from jarvis.contract import FinalResponse
from jarvis.fastpath.intents import VolumeSet
from jarvis.orchestrator.timing import Timing
from tests.orchestrator_rig import FakeBrain, Rig, command, make_rig, until


def test_should_fail_politely_when_the_brain_is_off_and_nothing_matches(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, brain=None)

    asyncio.run(rig.runner.run(command("do something", None)))

    assert len(rig.speaker.said) == 1
    assert "brain" in rig.speaker.said[0].lower()
    assert rig.states == ["error", "reply", "speaking", "idle"]
    [record] = rig.records()
    assert record["route"] == "brain"
    assert record["final"]["status"] == "failed"


def test_should_play_the_done_earcon_when_the_spoken_text_is_empty(tmp_path: Path) -> None:
    brain = FakeBrain(FinalResponse(status="success", spoken=""))
    rig = make_rig(tmp_path, brain=brain)

    asyncio.run(rig.runner.run(command("do something", None)))

    assert rig.speaker.earcons == ["done"]
    assert rig.speaker.said == []


def test_should_play_the_thinking_earcon_once_when_the_brain_is_slow(tmp_path: Path) -> None:
    async def scenario() -> Rig:
        brain = FakeBrain()
        brain.release = asyncio.Event()
        rig = make_rig(tmp_path, brain, Timing(thinking_after_s=0.0, deaf_tail_s=0.0))
        task = asyncio.create_task(rig.runner.run(command("do something", None, ended_ago=1.0)))
        try:
            await until(lambda: "thinking" in rig.speaker.earcons)
            brain.release.set()
            await task
        finally:
            task.cancel()
        return rig

    rig = asyncio.run(scenario())

    assert rig.speaker.earcons == ["thinking"]


def test_should_not_play_the_thinking_earcon_when_the_fast_path_is_quick(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, timing=Timing(thinking_after_s=5.0, deaf_tail_s=0.0))

    asyncio.run(rig.runner.run(command("set the volume to 40", VolumeSet(40))))

    assert rig.speaker.earcons == []


def test_should_record_a_cancelled_turn_and_reraise_when_the_task_is_cancelled(
    tmp_path: Path,
) -> None:
    async def scenario() -> Rig:
        brain = FakeBrain()
        brain.release = asyncio.Event()
        rig = make_rig(tmp_path, brain)
        task = asyncio.create_task(rig.runner.run(command("do something", None)))
        try:
            await asyncio.wait_for(brain.entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
        return rig

    rig = asyncio.run(scenario())

    [record] = rig.records()
    assert record["drop_reason"] == "cancelled"
    assert record["route"] == "brain"


def test_should_answer_with_an_internal_failure_when_the_brain_raises(tmp_path: Path) -> None:
    brain = FakeBrain()
    brain.error = RuntimeError("boom")
    rig = make_rig(tmp_path, brain=brain)

    asyncio.run(rig.runner.run(command("do something", None)))

    [record] = rig.records()
    assert record["final"]["status"] == "failed"
    assert record["final"]["error"]["code"] == "INTERNAL"
    assert len(rig.speaker.said) == 1
