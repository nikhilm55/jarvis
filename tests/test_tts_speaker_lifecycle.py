"""Tests for Speaker lifecycle: cancel() and close() semantics."""

import threading
import time

import numpy as np
import numpy.typing as npt
import pytest

from jarvis.tts.speaker import Speaker, SpeechHandle
from tests.tts_fakes import FakeEngine, FakeSink, make_speaker


def _playing(
    sinks: list[FakeSink],
    sink_class: type[FakeSink] = FakeSink,
) -> tuple[Speaker, threading.Event]:
    first_write = threading.Event()

    def on_write(block: npt.NDArray[np.float32], index: int) -> None:
        if index == 0:
            first_write.set()

    engine = FakeEngine()

    def custom_sink_factory(rate: int) -> FakeSink:
        sink = sink_class(rate, on_write=on_write)
        sinks.append(sink)
        return sink

    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=custom_sink_factory,
        clock=time.monotonic,
    )
    return speaker, first_write


def _live_tts_threads() -> list[threading.Thread]:
    tts_threads = [t for t in threading.enumerate() if t.name.startswith("jarvis-tts")]
    for t in tts_threads:
        t.join(2.0)
    return [t for t in tts_threads if t.is_alive()]


def test_should_close_sink_after_abort_when_cancelled_during_playback() -> None:
    sinks: list[FakeSink] = []
    speaker, first_write = _playing(sinks)

    handle = speaker.say("This is a long text that will take a while to play back.")
    assert first_write.wait(2.0)

    handle.cancel()

    sink = sinks[0]
    assert sink.close_called.wait(1.0)
    assert sink.aborted

    speaker.close()


def test_should_still_close_sink_when_abort_raises() -> None:
    class RaisingSink(FakeSink):
        def abort(self) -> None:
            super().abort()
            raise RuntimeError("device gone")

    sinks: list[FakeSink] = []
    speaker, first_write = _playing(sinks, sink_class=RaisingSink)

    handle = speaker.say("This is a long text that will take a while to play back.")
    assert first_write.wait(2.0)

    handle.cancel()

    sink = sinks[0]
    assert sink.close_called.wait(1.0)

    speaker.close()


def test_should_close_sink_when_playback_finishes_normally() -> None:
    sinks: list[FakeSink] = []
    engine = FakeEngine()
    speaker = make_speaker(engine, sinks)

    handle = speaker.say("One.")
    assert handle.wait(2.0)

    sink = sinks[0]
    assert sink.close_called.wait(1.0)

    speaker.close()


def test_should_cancel_silently_before_any_write_when_cancelled_during_synthesis() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)

    handle = speaker.say("One.")
    assert engine.entered.wait(2.0)

    handle.cancel()
    gate.set()
    assert handle.wait(1.0)

    total_blocks = sum(len(sink.blocks) for sink in sinks)
    assert total_blocks == 0
    assert handle.first_audio_s is None
    assert not handle.failed

    speaker.close()


def test_should_play_second_say_when_current_handle_cancelled() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)

    handle1 = speaker.say("One.")
    assert engine.entered.wait(2.0)

    handle1.cancel()
    gate.set()
    assert handle1.wait(1.0)

    handle2 = speaker.say("Two.")
    assert handle2.wait(2.0)

    assert handle2.first_audio_s is not None
    assert not handle2.failed
    assert engine.texts == ["One.", "Two."]

    speaker.close()


def test_should_end_current_handle_and_stop_worker_when_closed_while_speaking() -> None:
    sinks: list[FakeSink] = []
    speaker, first_write = _playing(sinks)

    handle = speaker.say("This is a long text that will take a while to play back.")
    assert first_write.wait(2.0)

    start = time.monotonic()
    speaker.close()
    elapsed = time.monotonic() - start
    assert elapsed < 2.0

    assert handle.wait(0)

    sink = sinks[0]
    assert sink.aborted
    assert sink.closed

    assert not _live_tts_threads()


def test_should_cancel_queued_jobs_and_never_synthesise_them_when_closed() -> None:
    gate = threading.Event()
    engine = FakeEngine(gate=gate)
    sinks: list[FakeSink] = []
    speaker = make_speaker(engine, sinks)

    handle1 = speaker.say("First.")
    handle2 = speaker.say("Second.")
    handle3 = speaker.say("Third.")

    assert engine.entered.wait(2.0)

    close_done = threading.Event()

    def do_close() -> None:
        speaker.close()
        close_done.set()

    closer = threading.Thread(target=do_close, daemon=True)
    closer.start()

    gate.set()
    closer.join(5.0)
    assert not closer.is_alive()

    assert handle1.wait(0)
    assert handle2.wait(0)
    assert handle3.wait(0)

    assert engine.texts == ["First."]

    assert not _live_tts_threads()


def _race_once() -> SpeechHandle | None:
    sinks: list[FakeSink] = []
    engine = FakeEngine()
    speaker = make_speaker(engine, sinks)

    result: dict[str, object] = {}

    def do_say() -> None:
        try:
            h = speaker.say("Hi.")
            result["handle"] = h
        except RuntimeError:
            result["handle"] = None

    def do_close() -> None:
        try:
            speaker.close()
        except RuntimeError as error:  # e.g. "cannot join thread before it is started"
            result["close_error"] = error

    thread_a = threading.Thread(target=do_say, daemon=True)
    thread_b = threading.Thread(target=do_close, daemon=True)

    thread_a.start()
    thread_b.start()

    thread_a.join(5.0)
    thread_b.join(5.0)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    assert "close_error" not in result
    handle = result.get("handle")
    if handle is not None and isinstance(handle, SpeechHandle):
        assert handle.wait(2.0)

    speaker.close()
    return handle if isinstance(handle, SpeechHandle) else None


def test_should_never_hang_or_raise_unexpectedly_when_say_races_close() -> None:
    for _ in range(60):
        _race_once()


def test_should_raise_runtime_error_when_say_after_close() -> None:
    sinks: list[FakeSink] = []
    engine = FakeEngine()
    speaker = make_speaker(engine, sinks)

    speaker.close()

    with pytest.raises(RuntimeError):
        speaker.say("Hello.")


def test_should_raise_runtime_error_when_earcon_after_close() -> None:
    sinks: list[FakeSink] = []
    engine = FakeEngine()
    speaker = make_speaker(engine, sinks)

    speaker.close()

    with pytest.raises(RuntimeError):
        speaker.earcon("wake")
