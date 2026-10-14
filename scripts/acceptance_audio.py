"""Acceptance helpers for audio source/sink timing and classification."""

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from jarvis.audio.sources import FRAME_SAMPLES, SAMPLE_RATE, Pcm
from jarvis.tts.earcons import EARCON_NAMES, earcon_samples
from jarvis.tts.sink import Sink

__all__ = [
    "Playback",
    "PlaybackLog",
    "QueueSource",
    "RecordingSink",
    "is_earcon_block",
    "recording_sink_factory",
]


@dataclass(frozen=True)
class Playback:
    """The first sound of one playback job."""

    at: float
    is_earcon: bool


class PlaybackLog:
    """Thread-safe log of playback start events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[Playback] = []

    def add(self, playback: Playback) -> None:
        """Record a playback event."""
        with self._lock:
            self._items.append(playback)

    def first_after(self, t: float, *, speech_only: bool = False) -> Playback | None:
        """Return the earliest recorded playback with at >= t."""
        with self._lock:
            for item in self._items:
                if item.at >= t and (not speech_only or not item.is_earcon):
                    return item
        return None

    def all(self) -> list[Playback]:
        """Return a copy of all recorded playbacks in insertion order."""
        with self._lock:
            return list(self._items)


def is_earcon_block(block: npt.NDArray[np.float32]) -> bool:
    """Check if a block matches the start of any known earcon."""
    if block.size == 0:
        return False
    return any(np.array_equal(block, earcon_samples(n)[: len(block)]) for n in EARCON_NAMES)


class RecordingSink:
    """Wraps a Sink; logs when its first block is written (earcon or speech)."""

    def __init__(
        self,
        inner: Sink,
        log: PlaybackLog,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._log = log
        self._clock = clock
        self._first = False

    def write(self, block: npt.NDArray[np.float32]) -> None:
        """Write a block, logging the first write timestamp."""
        if not self._first:
            self._first = True
            self._log.add(Playback(self._clock(), is_earcon_block(block)))
        self._inner.write(block)

    def abort(self) -> None:
        """Abort the inner sink."""
        self._inner.abort()

    def close(self) -> None:
        """Close the inner sink."""
        self._inner.close()


def recording_sink_factory(
    inner_factory: Callable[[int], Sink],
    log: PlaybackLog,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[[int], Sink]:
    """Return a factory that creates RecordingSink instances."""

    def factory(sample_rate: int) -> Sink:
        return RecordingSink(inner_factory(sample_rate), log, clock)

    return factory


class QueueSource:
    """A microphone stand-in: real-time frames, silence when nothing is queued."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._buffer: Pcm = np.zeros(0, dtype=np.int16)
        self._delivered = 0
        self._t0: float | None = None
        self._closed = False
        self.started = threading.Event()

    def feed(self, pcm: Pcm) -> float:
        """Queue int16 16 kHz samples; return the clock time of the first queued sample."""
        with self._lock:
            if self._t0 is None:
                raise RuntimeError("the source has not started")
            start_sample = self._delivered + len(self._buffer)
            self._buffer = np.concatenate((self._buffer, pcm))
            return self._t0 + start_sample / SAMPLE_RATE

    def frames(self) -> Iterator[Pcm]:
        """Yield FRAME_SAMPLES int16 samples per frame, each released once it has happened."""
        t0 = self._clock()
        with self._lock:
            self._t0 = t0
        self.started.set()
        index = 0
        while not self._closed:
            wait = t0 + (index + 1) * FRAME_SAMPLES / SAMPLE_RATE - self._clock()
            if wait > 0:
                self._sleep(wait)
            with self._lock:
                frame = self._buffer[:FRAME_SAMPLES]
                self._buffer = self._buffer[FRAME_SAMPLES:]
                self._delivered += FRAME_SAMPLES
            if len(frame) < FRAME_SAMPLES:
                frame = np.pad(frame, (0, FRAME_SAMPLES - len(frame)))
            yield frame
            index += 1

    def close(self) -> None:
        """Stop the source."""
        self._closed = True

    @property
    def delivered_s(self) -> float:
        """Seconds of audio delivered so far."""
        with self._lock:
            return self._delivered / SAMPLE_RATE
