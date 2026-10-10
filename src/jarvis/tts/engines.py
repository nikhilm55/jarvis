"""TTS engine abstractions and the spd-say implementation."""

import subprocess
import threading
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from jarvis.config import TtsSettings

Pcm = npt.NDArray[np.float32]


@runtime_checkable
class AudioEngine(Protocol):
    """Protocol for engines that produce PCM audio."""

    sample_rate: int

    def synthesize(self, text: str) -> Pcm: ...


@runtime_checkable
class DirectEngine(Protocol):
    """Protocol for engines that speak directly via a system TTS binary."""

    def speak(self, text: str) -> None: ...

    def cancel(self) -> None: ...


Engine = AudioEngine | DirectEngine


class SpdSayEngine:
    """Direct engine that shells out to the ``spd-say`` binary."""

    def __init__(
        self,
        binary: str = "spd-say",
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._binary = binary
        self._popen = popen
        self._run = run
        self._proc: Any = None
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        proc = self._popen(
            [self._binary, "-w", "--", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._proc = proc
        try:
            proc.wait()
        finally:
            with self._lock:
                self._proc = None

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        self._run(
            [self._binary, "-C"],
            check=False,
            timeout=2,
            capture_output=True,
        )
        proc.terminate()


def default_engine(settings: TtsSettings) -> Engine:
    """Return the engine selected by ``settings`` (spd-say for now)."""
    # Kokoro is wired in with the KokoroEngine commit.
    return SpdSayEngine()
