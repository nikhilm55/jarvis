import sys
import types
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from jarvis.tts.sink import BLOCK_S, AudioOutputError, Sink, SoundDeviceSink


class FakePortAudioError(Exception):
    pass


class FakeOutputStream:
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


class FakeSd:
    def __init__(self) -> None:
        self.streams: list[FakeOutputStream] = []
        self.fail_open: bool = False

    def make_module(self) -> types.ModuleType:
        module = types.ModuleType("sounddevice")
        streams = self.streams
        fail_open = self

        def make_stream(**kwargs: Any) -> FakeOutputStream:
            if fail_open.fail_open:
                raise FakePortAudioError("no device")
            stream = FakeOutputStream(**kwargs)
            streams.append(stream)
            return stream

        setattr(module, "OutputStream", make_stream)  # noqa: B010
        setattr(module, "PortAudioError", FakePortAudioError)  # noqa: B010
        return module


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> FakeSd:
    fake = FakeSd()
    monkeypatch.setitem(sys.modules, "sounddevice", fake.make_module())
    return fake


def test_should_open_stream_with_exact_kwargs_and_start_when_constructed(
    fake_sd: FakeSd,
) -> None:
    SoundDeviceSink(24000)

    stream = fake_sd.streams[0]
    assert stream.kwargs == {
        "samplerate": 24000,
        "channels": 1,
        "dtype": "float32",
        "latency": "low",
    }
    assert stream.calls == ["start"]


def test_should_forward_array_to_stream_when_write_called(
    fake_sd: FakeSd,
) -> None:
    sink = SoundDeviceSink(24000)
    block = np.array([0.1, -0.2, 0.3], dtype=np.float32)

    sink.write(block)

    stream = fake_sd.streams[0]
    assert len(stream.written) == 1
    np.testing.assert_array_equal(stream.written[0], block)


def test_should_call_stop_then_close_in_order_when_close_called(
    fake_sd: FakeSd,
) -> None:
    sink = SoundDeviceSink(24000)

    sink.close()

    stream = fake_sd.streams[0]
    assert stream.calls == ["start", "stop", "close"]


def test_should_call_abort_when_abort_called(
    fake_sd: FakeSd,
) -> None:
    sink = SoundDeviceSink(24000)

    sink.abort()

    stream = fake_sd.streams[0]
    assert stream.calls == ["start", "abort"]


def test_should_only_close_without_stop_when_close_after_abort(
    fake_sd: FakeSd,
) -> None:
    sink = SoundDeviceSink(24000)

    sink.abort()
    sink.close()

    stream = fake_sd.streams[0]
    assert stream.calls == ["start", "abort", "close"]


def test_should_raise_audio_output_error_when_port_audio_error_at_open(
    fake_sd: FakeSd,
) -> None:
    fake_sd.fail_open = True

    with pytest.raises(AudioOutputError) as exc_info:
        SoundDeviceSink(24000)

    assert "no device" in str(exc_info.value)


def test_should_raise_audio_output_error_when_sounddevice_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    with pytest.raises(AudioOutputError) as exc_info:
        SoundDeviceSink(24000)

    assert "sounddevice" in str(exc_info.value).lower()


def test_should_be_instance_of_sink_protocol(
    fake_sd: FakeSd,
) -> None:
    sink = SoundDeviceSink(24000)

    assert isinstance(sink, Sink)


def test_should_have_block_s_equal_to_0_05() -> None:
    assert BLOCK_S == 0.05


def test_should_only_close_stream_once_when_close_called_twice(
    fake_sd: FakeSd,
) -> None:
    sink = SoundDeviceSink(24000)

    sink.close()
    sink.close()

    stream = fake_sd.streams[0]
    assert stream.calls == ["start", "stop", "close"]
