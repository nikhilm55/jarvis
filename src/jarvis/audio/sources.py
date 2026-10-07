"""Audio sources: the microphone and WAV files, both as 16 kHz mono int16 frames."""

import queue
import threading
import time
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from jarvis.log import get_logger

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms

Pcm = npt.NDArray[np.int16]


class AudioFormatError(ValueError):
    """A WAV file is unreadable or not 16 kHz mono 16-bit."""


class AudioDeviceError(RuntimeError):
    """The microphone could not be opened."""


class AudioSource(Protocol):
    def frames(self) -> Iterator[Pcm]: ...

    def close(self) -> None: ...


class WavFileSource:
    """Yields a 16 kHz mono int16 WAV as 1280-sample frames; the last is zero-padded."""

    def __init__(
        self,
        path: Path,
        realtime: bool = False,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._path = path
        self._realtime = realtime
        self._clock = clock
        self._sleep = sleep
        self._closed = False

    def _read(self) -> Pcm:
        try:
            with wave.open(str(self._path), "rb") as wav:
                channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
                if rate != SAMPLE_RATE or channels != 1 or width != 2:
                    raise AudioFormatError(
                        f"{self._path}: need {SAMPLE_RATE} Hz mono 16-bit PCM, "
                        f"got {rate} Hz, {channels} channel(s), {width * 8}-bit"
                    )
                raw = wav.readframes(wav.getnframes())
        except (wave.Error, EOFError) as error:
            raise AudioFormatError(f"{self._path}: not a readable WAV file ({error})") from error
        return np.frombuffer(raw, dtype="<i2").astype(np.int16)

    def frames(self) -> Iterator[Pcm]:
        pcm = self._read()
        started = self._clock()
        for index, offset in enumerate(range(0, len(pcm), FRAME_SAMPLES)):
            if self._closed:
                return
            frame = pcm[offset : offset + FRAME_SAMPLES]
            if len(frame) < FRAME_SAMPLES:
                frame = np.pad(frame, (0, FRAME_SAMPLES - len(frame)))
            if self._realtime:
                wait = started + index * FRAME_SAMPLES / SAMPLE_RATE - self._clock()
                if wait > 0:
                    self._sleep(wait)
            yield frame

    def close(self) -> None:
        self._closed = True


class MicSource:
    """Microphone via sounddevice. Audio stays in RAM; nothing is written to disk (FR-AUD-05)."""

    def __init__(self, device: str | None = None) -> None:
        self._device = device
        self._blocks: queue.Queue[Pcm] = queue.Queue(maxsize=256)
        self._closed = threading.Event()

    def _callback(self, indata: Any, _frames: int, _time: object, status: object) -> None:
        if status:
            get_logger("audio").warning("audio input status", extra={"status": str(status)})
        try:
            self._blocks.put_nowait(np.array(indata[:, 0], dtype=np.int16))
        except queue.Full:
            get_logger("audio").warning("audio queue full; dropped a frame")

    def frames(self) -> Iterator[Pcm]:
        try:
            import sounddevice  # noqa: PLC0415 - lazy: importing jarvis.audio must not need PortAudio
        except (ImportError, OSError) as error:
            raise AudioDeviceError(f"sounddevice/PortAudio is unavailable: {error}") from error
        device: int | str | None = self._device
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        try:
            stream = sounddevice.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
                device=device,
                callback=self._callback,
            )
            stream.start()
        except Exception as error:  # sounddevice raises PortAudioError and friends
            raise AudioDeviceError(f"cannot open the microphone: {error}") from error
        try:
            while not self._closed.is_set():
                try:
                    yield self._blocks.get(timeout=0.1)
                except queue.Empty:
                    continue
        finally:
            stream.stop()
            stream.close()

    def close(self) -> None:
        self._closed.set()
