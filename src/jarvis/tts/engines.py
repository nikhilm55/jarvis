"""TTS engine abstractions and the spd-say implementation."""

import subprocess
import threading
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import httpx
import numpy as np
import numpy.typing as npt

from jarvis import models
from jarvis.config import TtsSettings
from jarvis.log import get_logger

logger = get_logger(__name__)

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
        self._speaking = False
        self._cancelled = False
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        with self._lock:
            self._speaking = True
            self._cancelled = False
        try:
            proc = self._popen(
                [self._binary, "-w", "--", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._proc = proc
                cancelled = self._cancelled
            if cancelled:
                proc.terminate()
            proc.wait()
        finally:
            with self._lock:
                self._proc = None
                self._speaking = False

    def cancel(self) -> None:
        with self._lock:
            if not self._speaking:
                return
            self._cancelled = True
            proc = self._proc
        if proc is None:
            return
        try:
            self._run(
                [self._binary, "-C"],
                check=False,
                timeout=2,
                capture_output=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("spd-say -C failed: %s", error)
        finally:
            proc.terminate()


class KokoroEngine:
    """Audio engine that synthesizes speech via the Kokoro ONNX runtime."""

    sample_rate: int = 24000

    def __init__(self, kokoro: Any, voice: str, speed: float) -> None:
        self._kokoro = kokoro
        self._voice = voice
        self._speed = speed
        self._lang = "en-gb" if voice.startswith("b") else "en-us"

    def synthesize(self, text: str) -> Pcm:
        audio, _rate = self._kokoro.create(
            text,
            voice=self._voice,
            speed=self._speed,
            lang=self._lang,
        )
        return np.asarray(audio, dtype=np.float32)


_KOKORO_FAILURES = (
    ImportError,
    OSError,
    ValueError,
    RuntimeError,
    httpx.HTTPError,
    models.ModelIntegrityError,
)


def _load_kokoro(settings: TtsSettings) -> KokoroEngine:
    from kokoro_onnx import Kokoro  # noqa: PLC0415

    model = models.ensure("kokoro-v1.0")
    voices = models.ensure("kokoro-voices-v1.0")
    return KokoroEngine(Kokoro(str(model), str(voices)), settings.voice, settings.speed)


def default_engine(settings: TtsSettings) -> Engine:
    """Return the engine selected by ``settings``.

    Prefers Kokoro when requested, falling back to spd-say on failure.
    """
    if settings.engine == "spd-say":
        return SpdSayEngine()
    try:
        return _load_kokoro(settings)
    except _KOKORO_FAILURES as error:
        logger.warning("Kokoro could not be loaded (%s); falling back to spd-say", error)
        return SpdSayEngine()
