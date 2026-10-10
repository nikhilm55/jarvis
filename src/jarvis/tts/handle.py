"""SpeechHandle: the caller's view of one queued utterance."""

import threading
from collections.abc import Callable


class SpeechHandle:
    """Handle to a single speech request; supports cancellation and timing."""

    def __init__(self, text: str, clock: Callable[[], float]) -> None:
        self.text = text
        self._clock = clock
        self._started_at: float = clock()
        self._lock = threading.Lock()
        self._ended = threading.Event()
        self._cancelled = threading.Event()
        self._first_audio: float | None = None
        self._failed: bool = False
        self._on_cancel: list[Callable[[], None]] = []

    @property
    def first_audio_s(self) -> float | None:
        """Seconds from creation until the first audio block was written."""
        with self._lock:
            return self._first_audio

    @property
    def is_speaking(self) -> bool:
        """True until the job finishes, fails, or is cancelled."""
        return not self._ended.is_set()

    @property
    def failed(self) -> bool:
        """True if the job ended in an error."""
        with self._lock:
            return self._failed

    @property
    def cancelled(self) -> bool:
        """True if cancel() has been called."""
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Idempotent cancellation; fires registered callbacks exactly once."""
        with self._lock:
            if self._cancelled.is_set():
                return
            self._cancelled.set()
            self._ended.set()
            callbacks = list(self._on_cancel)
            self._on_cancel.clear()
        for cb in callbacks:
            cb()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the job ends; return True if it did within timeout."""
        return self._ended.wait(timeout)

    def _note_first_audio(self) -> None:
        with self._lock:
            if self._first_audio is None:
                self._first_audio = self._clock() - self._started_at

    def _register_cancel(self, cb: Callable[[], None]) -> None:
        with self._lock:
            if self._cancelled.is_set():
                cb()
                return
            self._on_cancel.append(cb)

    def _clear_cancel(self) -> None:
        with self._lock:
            self._on_cancel.clear()

    def _fail(self) -> None:
        with self._lock:
            self._failed = True
        self._ended.set()

    def _finish(self) -> None:
        self._ended.set()
