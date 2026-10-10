import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import pytest

from jarvis.audio import (
    FRAME_SAMPLES,
    AudioDeviceError,
    AudioFormatError,
    MicSource,
    WavFileSource,
)


def _write_wav(
    path: Path, samples: np.ndarray, *, rate: int = 16000, channels: int = 1, width: int = 2
) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return path


def test_should_yield_full_frames_when_length_is_a_multiple_of_frame_size(tmp_path: Path) -> None:
    pcm = np.arange(FRAME_SAMPLES * 3, dtype=np.int16)
    source = WavFileSource(_write_wav(tmp_path / "a.wav", pcm))

    frames = list(source.frames())

    assert [len(f) for f in frames] == [FRAME_SAMPLES] * 3
    assert all(f.dtype == np.int16 and f.ndim == 1 for f in frames)
    assert np.array_equal(np.concatenate(frames), pcm)


def test_should_zero_pad_last_frame_when_length_is_not_a_multiple(tmp_path: Path) -> None:
    pcm = np.full(FRAME_SAMPLES + 100, 7, dtype=np.int16)
    source = WavFileSource(_write_wav(tmp_path / "a.wav", pcm))

    frames = list(source.frames())

    assert len(frames) == 2
    assert len(frames[1]) == FRAME_SAMPLES
    assert np.all(frames[1][:100] == 7)
    assert np.all(frames[1][100:] == 0)


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"rate": 44100}, "16000"),
        ({"channels": 2}, "mono"),
        ({"width": 1}, "16-bit"),
    ],
)
def test_should_reject_wav_when_format_is_not_16k_mono_int16(
    tmp_path: Path, kwargs: dict[str, int], needle: str
) -> None:
    width = kwargs.get("width", 2)
    pcm = np.zeros(FRAME_SAMPLES * 2, dtype=np.int16 if width == 2 else np.uint8)
    path = _write_wav(tmp_path / "bad.wav", pcm, **kwargs)

    with pytest.raises(AudioFormatError, match=needle):
        list(WavFileSource(path).frames())


def test_should_raise_clear_error_when_file_is_not_a_wav(tmp_path: Path) -> None:
    path = tmp_path / "bad.wav"
    path.write_bytes(b"not a wav at all")

    with pytest.raises(AudioFormatError, match="not a readable WAV"):
        list(WavFileSource(path).frames())


def test_should_pace_frames_to_the_clock_when_realtime(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["now"] += seconds

    pcm = np.zeros(FRAME_SAMPLES * 3, dtype=np.int16)
    source = WavFileSource(
        _write_wav(tmp_path / "a.wav", pcm),
        realtime=True,
        clock=lambda: clock["now"],
        sleep=sleep,
    )

    assert len(list(source.frames())) == 3
    assert clock["now"] == pytest.approx(0.16)  # frame 3 is released at 2 * 80 ms


def test_should_import_without_portaudio_and_fail_only_when_mic_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    mic = MicSource()  # constructing must not need PortAudio

    with pytest.raises(AudioDeviceError, match="sounddevice"):
        next(mic.frames())


class _FakeStream:
    """Stands in for sounddevice.InputStream: start() delivers two blocks via the callback."""

    opened: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeStream.opened.append(kwargs)

    def start(self) -> None:
        for value in (1, 2):
            block = np.full((FRAME_SAMPLES, 1), value, dtype=np.int16)
            self.kwargs["callback"](block, FRAME_SAMPLES, None, None)

    def stop(self) -> None: ...

    def close(self) -> None: ...


def test_should_stream_mono_frames_through_queue_and_stop_when_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeStream.opened.clear()
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=_FakeStream))
    mic = MicSource(device="3")

    frames = mic.frames()
    first, second = next(frames), next(frames)
    mic.close()

    assert list(frames) == []
    assert (first[0], second[0]) == (1, 2)
    assert first.shape == (FRAME_SAMPLES,) and first.dtype == np.int16
    opened = _FakeStream.opened[0]
    assert (opened["samplerate"], opened["channels"], opened["blocksize"]) == (16000, 1, 1280)
    assert (opened["dtype"], opened["device"]) == ("int16", 3)
