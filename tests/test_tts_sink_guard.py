"""The sink's write guard: a stalled device fails the speech instead of hanging the speaker."""

import sys
import threading
import types
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from jarvis.config import TtsSettings
from jarvis.tts.sink import AudioOutputError, SoundDeviceSink
from jarvis.tts.speaker import Speaker
from tests.tts_fakes import FakeEngine

StreamMaker = Callable[..., "FakeOutputStream"]
Installer = Callable[[StreamMaker], list["FakeOutputStream"]]


class FakePortAudioError(Exception):
    pass


class FakeOutputStream:
    """Records its calls and writes; a subclass can misbehave."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.written: list[npt.NDArray[np.float32]] = []
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def write(self, data: npt.NDArray[np.float32]) -> None:
        self.written.append(data)

    def abort(self) -> None:
        self.calls.append("abort")

    def stop(self) -> None:
        self.calls.append("stop")

    def close(self) -> None:
        self.calls.append("close")


class HangingStream(FakeOutputStream):
    """write() blocks until `release` is set, like the PipeWire stall."""

    def __init__(self, release: threading.Event, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._release = release

    def write(self, data: npt.NDArray[np.float32]) -> None:
        self._release.wait(5.0)


class FailingStream(FakeOutputStream):
    def write(self, data: npt.NDArray[np.float32]) -> None:
        raise RuntimeError("boom")


@pytest.fixture
def release() -> Iterator[threading.Event]:
    """Set at teardown so no hung fake write outlives its test."""
    event = threading.Event()
    yield event
    event.set()


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Installer:
    """Put a fake `sounddevice` in place; returns the list of streams it will create."""

    def _install(make: StreamMaker) -> list[FakeOutputStream]:
        streams: list[FakeOutputStream] = []

        def open_stream(**kwargs: Any) -> FakeOutputStream:
            stream = make(**kwargs)
            streams.append(stream)
            return stream

        module = types.ModuleType("sounddevice")
        setattr(module, "OutputStream", open_stream)  # noqa: B010
        setattr(module, "PortAudioError", FakePortAudioError)  # noqa: B010
        monkeypatch.setitem(sys.modules, "sounddevice", module)
        return streams

    return _install


BLOCK = np.full(1200, 0.1, dtype=np.float32)


def test_should_raise_stalled_and_abort_when_a_write_does_not_return(
    install: Installer, release: threading.Event
) -> None:
    streams = install(lambda **kw: HangingStream(release, **kw))
    sink = SoundDeviceSink(24000, write_timeout_s=0.05)

    with pytest.raises(AudioOutputError, match="stalled"):
        sink.write(BLOCK)

    assert "abort" in streams[0].calls


def test_should_close_without_stop_when_the_stream_stalled(
    install: Installer, release: threading.Event
) -> None:
    streams = install(lambda **kw: HangingStream(release, **kw))
    sink = SoundDeviceSink(24000, write_timeout_s=0.05)
    with pytest.raises(AudioOutputError):
        sink.write(BLOCK)

    sink.close()
    sink.close()

    assert streams[0].calls == ["start", "abort", "close"]


def test_should_forward_the_block_when_the_write_returns_in_time(install: Installer) -> None:
    streams = install(FakeOutputStream)
    sink = SoundDeviceSink(24000, write_timeout_s=2.0)

    sink.write(BLOCK)

    np.testing.assert_array_equal(streams[0].written[0], BLOCK)


def test_should_reraise_the_stream_error_when_write_raises(install: Installer) -> None:
    install(FailingStream)
    sink = SoundDeviceSink(24000)

    with pytest.raises(RuntimeError, match="boom"):
        sink.write(BLOCK)


def test_should_open_with_high_latency_when_none_is_given(install: Installer) -> None:
    streams = install(FakeOutputStream)

    SoundDeviceSink(24000)

    assert streams[0].kwargs["latency"] == "high"


def test_should_open_with_the_given_latency(install: Installer) -> None:
    streams = install(FakeOutputStream)

    SoundDeviceSink(24000, latency=0.05)

    assert streams[0].kwargs["latency"] == 0.05


def test_should_fail_the_handle_and_stay_usable_when_the_device_stalls(
    install: Installer, release: threading.Event
) -> None:
    def make(**kw: Any) -> FakeOutputStream:
        if not opened:  # only the first stream stalls
            opened.append(1)
            return HangingStream(release, **kw)
        return FakeOutputStream(**kw)

    opened: list[int] = []
    streams = install(make)

    def sink_factory(rate: int) -> SoundDeviceSink:
        return SoundDeviceSink(rate, write_timeout_s=0.05)

    speaker = Speaker(engine_factory=FakeEngine, sink_factory=sink_factory)
    try:
        stalled = speaker.say("hello there")
        assert stalled.wait(5.0)
        assert stalled.failed

        next_one = speaker.say("again")
        assert next_one.wait(5.0)
        assert not next_one.failed
        assert len(streams) == 2
    finally:
        speaker.close()


def test_should_open_the_stream_with_the_settings_latency_when_no_sink_factory(
    install: Installer,
) -> None:
    streams = install(FakeOutputStream)
    speaker = Speaker(TtsSettings(output_latency=0.05), engine_factory=FakeEngine)
    try:
        handle = speaker.say("hi")
        assert handle.wait(5.0)
    finally:
        speaker.close()

    assert streams[0].kwargs["latency"] == 0.05
