"""Tests for the Listener: silent drops, an empty transcript, Stop and an STT failure."""

import asyncio
from pathlib import Path

import pytest

from jarvis.orchestrator.listener import NOT_UNDERSTOOD, STT_DOWN
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


def test_should_speak_not_understood_when_transcript_is_empty(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=[""])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.speaker.said == [NOT_UNDERSTOOD]
    assert rig.submitted == []
    records = rig.records()
    assert len(records) == 1
    assert records[0]["drop_reason"] == "empty transcript"


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
