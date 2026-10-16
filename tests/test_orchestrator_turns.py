"""Tests for jarvis.orchestrator.turns: the fast path and the brain fallback."""

import asyncio
import json
from pathlib import Path

from jarvis import paths
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


def test_should_list_the_gate_decisions_of_a_fast_path_turn_in_the_activity_record(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)

    asyncio.run(rig.runner.run(command("open calculator", OpenApp("calculator"))))
    asyncio.run(rig.runner.run(command("set the volume to 40", VolumeSet(40))))

    first, second = rig.records()
    assert first["policy_decisions"] == [
        {"tool": "desktop.open_app", "allowed": True, "reason": "allowed: T1", "tier": "T1"}
    ]
    assert [d["tool"] for d in second["policy_decisions"]] == ["desktop.volume_set"]
    assert first["turn_id"] != second["turn_id"]
    audit = (paths.data_dir() / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in audit.splitlines()]
    decided = [r["turn_id"] for r in rows if r["msg"] == "policy decision"]
    assert decided == [first["turn_id"], second["turn_id"]]
