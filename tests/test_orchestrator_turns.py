"""Tests for jarvis.orchestrator.turns: the fast path and the brain fallback."""

import asyncio
from pathlib import Path

from jarvis.desktop.client import DesktopError
from jarvis.fastpath.intents import OpenApp, VolumeSet
from tests.orchestrator_rig import FakeBrain, command, make_rig


def test_should_speak_and_record_a_fast_path_turn_when_the_intent_is_known(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)

    asyncio.run(rig.runner.run(command("set the volume to 40", VolumeSet(40))))

    assert rig.speaker.said == ["Volume 40 percent."]
    assert rig.desktop_events == ["desktop.volume_set"]
    [record] = rig.records()
    assert record["route"] == "fastpath"
    assert record["command"] == "set the volume to 40"
    assert record["final"]["spoken"] == "Volume 40 percent."
    assert record["durations_ms"]["stt"] == 120
    assert "total" in record["durations_ms"]
    assert record["drop_reason"] is None


def test_should_emit_hud_states_in_order_when_a_fast_path_turn_runs(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)

    asyncio.run(rig.runner.run(command("set the volume to 40", VolumeSet(40))))

    assert rig.states == ["acting", "reply", "speaking", "idle"]


def test_should_fall_through_to_the_brain_when_the_fast_path_declines(tmp_path: Path) -> None:
    brain = FakeBrain()
    rig = make_rig(tmp_path, brain=brain, error=DesktopError("NOT_FOUND", "no such app"))

    asyncio.run(rig.runner.run(command("open calculator", OpenApp("calculator"))))

    assert rig.speaker.said == ["Handled by the brain."]
    assert len(brain.envelopes) == 1
    [record] = rig.records()
    assert record["route"] == "brain"
