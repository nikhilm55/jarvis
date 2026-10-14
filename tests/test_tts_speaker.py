"""Speaker: queueing, lazy engine and sentence-by-sentence playback."""

import threading

from jarvis.tts.speaker import Speaker
from tests.tts_fakes import FakeEngine, FakeSink, make_speaker


def test_should_return_before_synthesis_finishes_when_engine_gated() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("Hello.")
        assert handle.is_speaking
        assert handle.wait(0.05) is False
        gate.set()
        assert handle.wait(5.0) is True
        assert handle.is_speaking is False
    finally:
        speaker.close()


def test_should_call_engine_factory_exactly_once_when_two_says() -> None:
    calls = 0

    def factory() -> FakeEngine:
        nonlocal calls
        calls += 1
        return FakeEngine()

    speaker = Speaker(engine_factory=factory, sink_factory=FakeSink)
    try:
        assert calls == 0
        h1 = speaker.say("One.")
        h1.wait(5.0)
        h2 = speaker.say("Two.")
        h2.wait(5.0)
        assert calls == 1
    finally:
        speaker.close()


def test_should_play_every_sentence_in_order_when_three_sentences() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("One. Two. Three.")
        assert handle.wait(5.0) is True
        assert engine.texts == ["One.", "Two.", "Three."]
        sink = sinks[0]
        fills = list(dict.fromkeys(round(float(blk[0]), 3) for blk in sink.blocks))
        assert fills == [0.1, 0.2, 0.3]
    finally:
        speaker.close()
