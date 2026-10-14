import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from jarvis.audio.sources import FRAME_SAMPLES
from jarvis.tts.earcons import earcon_samples

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "acceptance_audio", ROOT / "scripts" / "acceptance_audio.py"
)
assert spec and spec.loader
audio = importlib.util.module_from_spec(spec)
sys.modules["acceptance_audio"] = audio
spec.loader.exec_module(audio)


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps.append(seconds)


class FakeSink:
    def __init__(self) -> None:
        self.writes: list[object] = []
        self.aborts: list[None] = []
        self.closes: list[None] = []

    def write(self, data: object) -> None:
        self.writes.append(data)

    def abort(self) -> None:
        self.aborts.append(None)

    def close(self) -> None:
        self.closes.append(None)


def test_should_raise_runtime_error_when_feed_before_start() -> None:
    clock = FakeClock()
    source = audio.QueueSource(clock=clock, sleep=clock.sleep)
    with pytest.raises(RuntimeError):
        source.feed(np.zeros(100, dtype=np.int16))


def test_should_return_t0_plus_position_when_feed_after_frames_delivered() -> None:
    clock = FakeClock()
    source = audio.QueueSource(clock=clock, sleep=clock.sleep)
    gen = source.frames()
    next(gen)
    next(gen)
    first = np.zeros(16000, dtype=np.int16)
    t = source.feed(first)
    assert t == pytest.approx(0.16)  # t0 is 0.0 on the fake clock
    second = np.zeros(16000, dtype=np.int16)
    t2 = source.feed(second)
    assert t2 == pytest.approx(t + 1.0)


def test_should_yield_fed_samples_in_order_when_across_frames() -> None:
    clock = FakeClock()
    source = audio.QueueSource(clock=clock, sleep=clock.sleep)
    gen = source.frames()
    f1 = next(gen)  # starts the source; the samples are fed from here
    assert not f1.any()
    source.feed(np.arange(1, 2001, dtype=np.int16))
    f1 = next(gen)
    assert len(f1) == FRAME_SAMPLES
    assert f1[0] == 1
    assert f1[FRAME_SAMPLES - 1] == FRAME_SAMPLES
    f2 = next(gen)
    assert f2[0] == FRAME_SAMPLES + 1
    assert f2[719] == 2000
    assert f2[720] == 0


def test_should_yield_zero_frames_when_idle() -> None:
    clock = FakeClock()
    source = audio.QueueSource(clock=clock, sleep=clock.sleep)
    gen = source.frames()
    frame = next(gen)
    assert np.all(frame == 0)


def test_should_sleep_frame_period_when_clock_has_not_advanced() -> None:
    clock = FakeClock()
    source = audio.QueueSource(clock=clock, sleep=clock.sleep)
    gen = source.frames()
    next(gen)
    assert clock.sleeps == [0.08]


def test_should_stop_generator_when_closed() -> None:
    clock = FakeClock()
    source = audio.QueueSource(clock=clock, sleep=clock.sleep)
    gen = source.frames()
    next(gen)
    source.close()
    with pytest.raises(StopIteration):
        next(gen)


def test_should_order_playbacks_when_first_after_called() -> None:
    log = audio.PlaybackLog()
    log.add(audio.Playback(at=1.0, is_earcon=False))
    log.add(audio.Playback(at=0.5, is_earcon=True))
    p = log.first_after(0.0)  # the first one recorded that is not before t
    assert p is not None
    assert p.at == 1.0
    p2 = log.first_after(0.6)
    assert p2 is not None
    assert p2.at == 1.0


def test_should_filter_speech_only_when_first_after_speech_only() -> None:
    log = audio.PlaybackLog()
    log.add(audio.Playback(at=0.5, is_earcon=True))
    log.add(audio.Playback(at=1.0, is_earcon=False))
    p = log.first_after(0.0, speech_only=True)
    assert p is not None
    assert p.at == 1.0
    assert p.is_earcon is False


def test_should_log_once_when_multiple_writes() -> None:
    log = audio.PlaybackLog()
    clock = FakeClock()
    inner = FakeSink()
    sink = audio.RecordingSink(inner, log, clock)
    block = np.zeros(10, dtype=np.float32)
    sink.write(block)
    sink.write(block)
    sink.write(block)
    assert len(log.all()) == 1
    assert len(inner.writes) == 3


def test_should_classify_earcon_when_first_block_matches() -> None:
    log = audio.PlaybackLog()
    clock = FakeClock()
    inner = FakeSink()
    sink = audio.RecordingSink(inner, log, clock)
    block = earcon_samples("wake")[:1200]
    sink.write(block)
    pb = log.all()[0]
    assert pb.is_earcon is True


def test_should_classify_speech_when_first_block_does_not_match() -> None:
    log = audio.PlaybackLog()
    clock = FakeClock()
    inner = FakeSink()
    sink = audio.RecordingSink(inner, log, clock)
    block = np.full(1200, 0.5, dtype=np.float32)
    sink.write(block)
    pb = log.all()[0]
    assert pb.is_earcon is False


def test_should_delegate_calls_when_sink_used() -> None:
    log = audio.PlaybackLog()
    clock = FakeClock()
    inner = FakeSink()
    sink = audio.RecordingSink(inner, log, clock)
    block = np.zeros(10, dtype=np.float32)
    sink.write(block)
    sink.abort()
    sink.close()
    assert len(inner.writes) == 1
    assert len(inner.aborts) == 1
    assert len(inner.closes) == 1


def test_should_build_sink_with_rate_when_factory_called() -> None:
    log = audio.PlaybackLog()
    clock = FakeClock()

    def inner_factory(rate: int) -> FakeSink:
        return FakeSink()

    factory = audio.recording_sink_factory(inner_factory, log, clock)
    sink = factory(16000)
    assert isinstance(sink, audio.RecordingSink)
