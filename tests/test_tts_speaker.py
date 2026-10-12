"""Speaker: queueing, lazy engine and sentence-by-sentence playback."""

import threading
import time

import numpy as np
import numpy.typing as npt
import pytest

from jarvis.tts.earcons import EARCON_RATE, earcon_samples
from jarvis.tts.sink import BLOCK_S, AudioOutputError
from jarvis.tts.speaker import Speaker
from tests.tts_fakes import FakeDirect, FakeEngine, FakeSink, MutableClock, make_speaker


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


def test_should_stream_second_sentence_while_first_playing_when_on_write_waits() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    outcome: list[bool] = []

    def on_write(block: npt.NDArray[np.float32], index: int) -> None:
        if index == 0:
            outcome.append(engine.second_started.wait(5.0))

    sink = FakeSink(24000, on_write=on_write)
    sinks.append(sink)
    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=lambda rate: sink,
    )
    try:
        handle = speaker.say("One. Two.")
        assert handle.wait(5.0) is True
        assert len(outcome) == 1
        assert outcome[0] is True
    finally:
        speaker.close()


def test_should_limit_block_size_when_writing() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("One. Two. Three.")
        assert handle.wait(5.0) is True
        max_samples = int(24000 * BLOCK_S)
        for blk in sinks[0].blocks:
            assert len(blk) <= max_samples
    finally:
        speaker.close()


def test_should_use_injected_clock_for_first_audio_s_when_clock_set() -> None:
    clock = MutableClock(10.0)
    engine = FakeEngine(on_call=lambda: setattr(clock, "now", 10.25))
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks, clock)
    try:
        handle = speaker.say("One.")
        assert handle.wait(5.0) is True
        assert handle.first_audio_s == pytest.approx(0.25)
    finally:
        speaker.close()


def test_should_have_none_first_audio_s_when_engine_gated_before_write() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("One.")
        assert handle.first_audio_s is None
        gate.set()
        assert handle.wait(5.0) is True
    finally:
        speaker.close()


def test_should_cancel_during_playback_when_long_text() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    first_write = threading.Event()

    def on_write(block: npt.NDArray[np.float32], index: int) -> None:
        if index == 0:
            first_write.set()

    sink = FakeSink(24000, on_write=on_write)
    sinks.append(sink)
    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=lambda rate: sink,
    )
    try:
        handle = speaker.say("One. Two. Three. Four. Five. Six.")
        assert first_write.wait(5.0) is True
        start = time.monotonic()
        handle.cancel()
        assert sink.abort_called.wait(0.3) is True
        assert time.monotonic() - start < 0.3
        assert handle.wait(0.3) is True
        assert sink.writes_after_abort == 0
        assert len(engine.texts) < 6
        handle.cancel()
    finally:
        speaker.close()


def test_should_be_idempotent_and_safe_when_cancel_finished_handle() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("One.")
        assert handle.wait(5.0) is True
        handle.cancel()
        assert handle.is_speaking is False
        handle.cancel()
        assert handle.is_speaking is False
    finally:
        speaker.close()


def test_should_queue_second_say_after_first_when_first_gated() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        h1 = speaker.say("First.")
        h2 = speaker.say("Second.")
        assert engine.entered.wait(5.0) is True
        assert h2.is_speaking is True
        assert engine.texts == ["First."]
        gate.set()
        assert h1.wait(5.0) is True
        assert h2.wait(5.0) is True
        assert engine.texts == ["First.", "Second."]
        assert len(sinks) == 2
    finally:
        speaker.close()


def test_should_skip_queued_handle_when_cancelled_before_start() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        h1 = speaker.say("First.")
        h2 = speaker.say("Second.")
        h2.cancel()
        gate.set()
        assert h1.wait(5.0) is True
        assert h2.wait(5.0) is True
        assert engine.texts == ["First."]
    finally:
        speaker.close()


def test_should_mark_failed_when_engine_raises() -> None:
    engine = FakeEngine(fail_on="Boom.")
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("Boom.")
        assert handle.wait(5.0) is True
        assert handle.failed is True
        assert handle.is_speaking is False
        h2 = speaker.say("Fine.")
        assert h2.wait(5.0) is True
        assert h2.failed is False
    finally:
        speaker.close()


def test_should_mark_failed_when_sink_factory_raises_once() -> None:
    engine = FakeEngine()
    calls = 0

    def flaky_factory(rate: int) -> FakeSink:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AudioOutputError("no device")
        return FakeSink(rate)

    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=flaky_factory,
    )
    try:
        handle = speaker.say("One.")
        assert handle.wait(5.0) is True
        assert handle.failed is True
        h2 = speaker.say("Two.")
        assert h2.wait(5.0) is True
        assert h2.failed is False
    finally:
        speaker.close()


def test_should_stop_worker_when_close_called() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say("One.")
        assert handle.wait(5.0) is True
    finally:
        speaker.close()
    names = [t.name for t in threading.enumerate()]
    assert "jarvis-tts" not in names


@pytest.mark.parametrize("text", ["", "   \n\t"], ids=["empty", "whitespace"])
def test_should_finish_immediately_when_text_has_nothing_to_say(text: str) -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        handle = speaker.say(text)
        assert handle.is_speaking is False
        assert handle.failed is False
        assert handle.first_audio_s is None
        assert handle.wait(0) is True
        assert engine.texts == []
    finally:
        speaker.close()


def test_should_play_earcon_when_known_name() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    rates: list[int] = []

    def sink_factory(rate: int) -> FakeSink:
        rates.append(rate)
        sink = FakeSink(rate)
        sinks.append(sink)
        return sink

    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=sink_factory,
    )
    try:
        handle = speaker.earcon("wake")
        assert handle.wait(5.0) is True
        assert handle.first_audio_s is not None
        assert len(sinks) == 1
        assert len(sinks[0].blocks) >= 1
        assert rates == [EARCON_RATE]
        assert np.array_equal(np.concatenate(sinks[0].blocks), earcon_samples("wake"))
    finally:
        speaker.close()


def test_should_raise_value_error_when_earcon_unknown() -> None:
    engine = FakeEngine()
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)
    try:
        with pytest.raises(ValueError):
            speaker.earcon("bogus")
    finally:
        speaker.close()


def test_should_use_direct_engine_when_say_called() -> None:
    direct = FakeDirect()
    speaker = Speaker(
        engine_factory=lambda: direct,
        sink_factory=FakeSink,
    )
    try:
        handle = speaker.say("Hello there. Bye.")
        assert handle.wait(5.0) is True
        assert direct.spoken == ["Hello there. Bye."]
        assert handle.first_audio_s is not None
    finally:
        speaker.close()


def test_should_cancel_direct_engine_when_handle_cancelled() -> None:
    direct = FakeDirect(block=True)
    speaker = Speaker(
        engine_factory=lambda: direct,
        sink_factory=FakeSink,
    )
    try:
        handle = speaker.say("Hello there. Bye.")
        assert direct.entered.wait(5.0) is True
        handle.cancel()
        assert handle.wait(0.3) is True
        assert direct.cancelled.is_set() is True
    finally:
        speaker.close()
