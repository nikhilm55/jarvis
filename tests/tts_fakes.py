"""Fakes shared by the speaker tests: engine, sink and clock; no audio, no network."""

import threading
import time
from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from jarvis.tts.engines import AudioEngine, DirectEngine
from jarvis.tts.speaker import Speaker

WriteCallback = Callable[[npt.NDArray[np.float32], int], None]


class FakeEngine:
    """AudioEngine fake: records texts, returns deterministic PCM, optional gating/fail."""

    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        fail_on: str | None = None,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self.sample_rate = 24000
        self._on_call = on_call
        self._lock = threading.Lock()
        self.texts: list[str] = []
        self._gate = gate
        self._fail_on = fail_on
        self.entered = threading.Event()
        self.second_started = threading.Event()

    def synthesize(self, text: str) -> npt.NDArray[np.float32]:
        self.entered.set()
        if self._on_call is not None:
            self._on_call()
        with self._lock:
            index = len(self.texts)
            self.texts.append(text)
        if self._gate is not None:
            self._gate.wait(5.0)
        if index == 1:
            self.second_started.set()
        if self._fail_on is not None and text == self._fail_on:
            raise RuntimeError("boom")
        fill = 0.1 * (1 + index)
        return np.full(int(self.sample_rate * 0.2), fill, dtype=np.float32)


class FakeSink:
    """Sink fake: records blocks, paces writes, optional on_write callback."""

    def __init__(
        self,
        rate: int,
        on_write: WriteCallback | None = None,
    ) -> None:
        self.rate = rate
        self.blocks: list[npt.NDArray[np.float32]] = []
        self.aborted = False
        self.abort_called = threading.Event()
        self.writes_after_abort = 0
        self.closed = False
        self.close_called = threading.Event()
        self._on_write = on_write
        self._pace = threading.Event()

    def write(self, block: npt.NDArray[np.float32]) -> None:
        index = len(self.blocks)
        self.blocks.append(block)
        if self.aborted:
            self.writes_after_abort += 1
        if self._on_write is not None:
            self._on_write(block, index)
        self._pace.wait(0.005)

    def abort(self) -> None:
        self.aborted = True
        self.abort_called.set()

    def close(self) -> None:
        self.closed = True
        self.close_called.set()


class FakeDirect:
    """DirectEngine fake: records spoken texts, cancellable blocking speak."""

    def __init__(self, *, block: bool = False) -> None:
        self.spoken: list[str] = []
        self._block = block
        self._cancel = threading.Event()
        self.entered = threading.Event()
        self.cancelled = threading.Event()

    def speak(self, text: str) -> None:
        self.entered.set()
        self.spoken.append(text)
        if self._block:
            self._cancel.wait(5.0)

    def cancel(self) -> None:
        self.cancelled.set()
        self._cancel.set()


class MutableClock:
    """Tiny clock object with a settable `now`."""

    def __init__(self, value: float = 0.0) -> None:
        self.now = value

    def __call__(self) -> float:
        return self.now


def make_speaker(
    engine: AudioEngine | DirectEngine,
    sinks: list[FakeSink],
    clock: Callable[[], float] | None = None,
) -> Speaker:
    def sink_factory(rate: int) -> FakeSink:
        sink = FakeSink(rate)
        sinks.append(sink)
        return sink

    return Speaker(
        engine_factory=lambda: engine,
        sink_factory=sink_factory,
        clock=clock if clock is not None else time.monotonic,
    )
