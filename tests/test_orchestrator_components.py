"""Tests for jarvis.orchestrator.components: start-up and close order of the children."""

import asyncio

import pytest

from jarvis.brain import BrainUnavailable
from jarvis.orchestrator.components import Components, close_components, start_components
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.voice import Voice
from jarvis.stt import SttUnavailable
from tests.core_feed import Feed
from tests.recording_rig import (
    RecordingBrain,
    RecordingDesktop,
    RecordingService,
    RecordingSpeaker,
    RecordingTranscriber,
)


class NamedService:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    async def start(self) -> None:
        self.events.append(f"{self.name}.start")

    async def close(self) -> None:
        self.events.append(f"{self.name}.close")


def make_parts(
    events: list[str],
    *,
    brain: RecordingBrain | None = None,
    transcriber: RecordingTranscriber | None = None,
    services: list[NamedService] | None = None,
) -> Components:
    feed = Feed()
    speaker = RecordingSpeaker(events)
    return Components(
        source=feed,
        segmenter=feed,
        transcriber=transcriber or RecordingTranscriber([], events),
        speaker=speaker,
        voice=Voice(speaker, Timing(deaf_tail_s=0.0)),
        desktop=RecordingDesktop(events),
        brain=brain,
        services=services if services is not None else [RecordingService(events)],
    )


def test_should_start_services_before_the_transcriber_and_the_brain() -> None:
    events: list[str] = []
    parts = make_parts(events, brain=RecordingBrain(events))

    problem = asyncio.run(start_components(parts))

    assert problem is None
    assert events[0] == "service.start"
    assert set(events[1:]) == {"transcriber.start", "brain.start"}


def test_should_start_only_services_and_transcriber_when_there_is_no_brain() -> None:
    events: list[str] = []

    problem = asyncio.run(start_components(make_parts(events)))

    assert problem is None
    assert events == ["service.start", "transcriber.start"]


def test_should_return_the_problem_when_the_brain_is_unavailable() -> None:
    events: list[str] = []
    brain = RecordingBrain(events)
    brain.fail_start = BrainUnavailable("not logged in", ["Run claude and log in."])

    problem = asyncio.run(start_components(make_parts(events, brain=brain)))

    assert problem is brain.fail_start
    assert "transcriber.start" in events


def test_should_raise_when_the_transcriber_cannot_start() -> None:
    events: list[str] = []
    transcriber = RecordingTranscriber([], events)
    transcriber.fail_start = SttUnavailable("no server", "install it")

    with pytest.raises(SttUnavailable):
        asyncio.run(start_components(make_parts(events, transcriber=transcriber)))


def test_should_close_brain_desktop_speaker_transcriber_then_services() -> None:
    events: list[str] = []
    parts = make_parts(events, brain=RecordingBrain(events))

    asyncio.run(close_components(parts))

    assert events == [
        "brain.close",
        "desktop.close",
        "speaker.close",
        "transcriber.close",
        "service.close",
    ]


def test_should_close_services_in_reverse_order() -> None:
    events: list[str] = []
    parts = make_parts(events, services=[NamedService("a", events), NamedService("b", events)])

    asyncio.run(close_components(parts))

    assert events[-2:] == ["b.close", "a.close"]


def test_should_keep_closing_when_one_child_fails() -> None:
    class ExplodingBrain(RecordingBrain):
        async def close(self) -> None:
            raise RuntimeError("boom")

    events: list[str] = []
    parts = make_parts(events, brain=ExplodingBrain(events))

    asyncio.run(close_components(parts))

    assert events == ["desktop.close", "speaker.close", "transcriber.close", "service.close"]
