"""Tests for the Listener: silent drops, an empty transcript after a wake, Stop, an STT failure."""

import asyncio
from pathlib import Path

import pytest

from jarvis.orchestrator.listener import STT_DOWN
from tests.listener_rig import make_listener_rig, seg


def test_should_be_silent_when_gate_rejects_first_word(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=["Hello there, how are you"])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.submitted == []
    assert rig.speaker.said == []
    assert rig.speaker.earcons == []
    assert rig.states == []
    records = rig.records()
    assert len(records) == 1
    assert records[0]["route"] == "dropped"
    assert records[0]["drop_reason"] == "gate rejected the first word"
    assert records[0]["raw_transcript"] == "Hello there, how are you"


def test_should_end_silently_when_transcript_is_empty_right_after_a_wake(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=[""])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.speaker.said == []
    assert rig.speaker.earcons == []
    assert rig.states == []
    assert rig.submitted == []
    records = rig.records()
    assert len(records) == 1
    assert records[0]["route"] == "dropped"
    assert records[0]["drop_reason"] == "empty transcript"


def test_should_stay_silent_and_log_when_transcript_is_whitespace_only(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=["  \n "])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.speaker.said == []
    assert rig.records()[0]["drop_reason"] == "empty transcript"


def test_should_still_drop_a_non_empty_transcript_the_gate_rejects(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=["the weather is nice"])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.speaker.said == []
    assert rig.records()[0]["drop_reason"] == "gate rejected the first word"
    assert rig.records()[0]["raw_transcript"] == "the weather is nice"


@pytest.mark.parametrize("text", ["Jarvis, stop", "Jarvis, cancel", "Jarvis, never mind"])
def test_should_stop_when_stop_intent_is_received(tmp_path: Path, text: str) -> None:
    rig = make_listener_rig(tmp_path, texts=[text])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.stops == 1
    assert rig.submitted == []


def test_should_survive_when_transcriber_raises(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=[RuntimeError("engine down"), "Jarvis, open Teams."])
    asyncio.run(rig.listener.handle(seg()))
    assert "error" in rig.states
    assert rig.speaker.said == [STT_DOWN]
    assert rig.submitted == []
    asyncio.run(rig.listener.handle(seg()))
    assert len(rig.submitted) == 1
