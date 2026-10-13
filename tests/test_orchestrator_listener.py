"""Tests for the Listener wake path: gating, dropping, the fast-path match and Stop."""

import asyncio
from pathlib import Path

import pytest

from jarvis.fastpath.intents import VolumeSet
from jarvis.orchestrator.listener import WAKE_PROMPT
from tests.listener_rig import make_listener_rig, seg


def test_should_ignore_when_segment_is_tainted(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=[])
    asyncio.run(rig.listener.handle(seg(tainted=True)))
    assert rig.transcriber.prompts == []
    assert rig.records() == []


def test_should_ignore_when_wake_score_is_below_threshold(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=[])
    asyncio.run(rig.listener.handle(seg(score=0.001)))
    assert rig.transcriber.prompts == []
    assert rig.records() == []


def test_should_drop_when_silence_before_ms_is_under_400(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=[])
    asyncio.run(rig.listener.handle(seg(silence_ms=300)))
    assert rig.transcriber.prompts == []
    records = rig.records()
    assert len(records) == 1
    assert records[0]["route"] == "dropped"
    assert records[0]["drop_reason"] == "silence_before_ms<400"
    assert rig.submitted == []


def test_should_transcribe_with_wake_prompt_when_wake_path_is_taken(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=["Jarvis, open Teams."])
    asyncio.run(rig.listener.handle(seg()))
    assert rig.transcriber.prompts == [WAKE_PROMPT]


def test_should_submit_command_when_transcript_is_accepted(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=["Jarvis, what's on my calendar today?"])
    asyncio.run(rig.listener.handle(seg()))
    assert len(rig.submitted) == 1
    cmd = rig.submitted[0]
    assert cmd.text == "what's on my calendar today?"
    assert cmd.raw == "Jarvis, what's on my calendar today?"
    assert cmd.intent is None
    assert cmd.speech_ended_at == pytest.approx(100.0 - 0.7)
    assert cmd.stt_ms >= 0
    assert rig.states == ["transcript"]
    assert rig.records() == []
    assert rig.speaker.said == []


def test_should_carry_intent_when_fast_path_matches(tmp_path: Path) -> None:
    rig = make_listener_rig(tmp_path, texts=["Jarvis, set the volume to 40"])
    asyncio.run(rig.listener.handle(seg()))
    assert len(rig.submitted) == 1
    assert rig.submitted[0].intent == VolumeSet(40)
