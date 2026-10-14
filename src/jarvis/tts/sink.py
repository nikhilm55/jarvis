"""Audio output sink for the Jarvis TTS pipeline."""

import threading
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from jarvis.tts.engines import Pcm

BLOCK_S = 0.05


class AudioOutputError(RuntimeError):
    """Raised when the audio output device cannot be used."""


@runtime_checkable
class Sink(Protocol):
    """Protocol describing a writable audio sink."""

    def write(self, block: Pcm) -> None:
        """Write one block of PCM samples to the output device."""

    def abort(self) -> None:
        """Abort the current playback immediately."""

    def close(self) -> None:
        """Release the underlying audio stream."""


class SoundDeviceSink:
    """Sink backed by the sounddevice library."""

    def __init__(
        self,
        sample_rate: int,
        latency: str | float = "high",
        write_timeout_s: float = 2.0,
    ) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415
        except (ImportError, OSError) as error:
            raise AudioOutputError(f"sounddevice is unavailable: {error}") from error

        try:
            self._stream: Any = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                latency=latency,
            )
            self._stream.start()
        except sd.PortAudioError as error:
            raise AudioOutputError(f"cannot open the audio output: {error}") from error

        self._aborted = False
        self._closed = False
        self._write_timeout_s = write_timeout_s

    def _guarded(self, action: Callable[[], None], timeout_s: float) -> bool:
        """Run action in a daemon thread, join with timeout, re-raise on error."""
        result: list[BaseException | None] = [None]

        def _runner() -> None:
            try:
                action()
            except BaseException as exc:
                result[0] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout_s)
        if thread.is_alive():
            return False
        if result[0] is not None:
            raise result[0]
        return True

    def write(self, block: Pcm) -> None:
        """Write one block of PCM samples to the output device."""
        if not self._guarded(lambda: self._stream.write(block), self._write_timeout_s):
            self._aborted = True
            self._guarded(self._stream.abort, 1.0)
            raise AudioOutputError(
                f"audio output stalled: a write did not return within {self._write_timeout_s} s"
            )

    def abort(self) -> None:
        """Abort the current playback immediately."""
        self._guarded(self._stream.abort, 1.0)
        self._aborted = True

    def close(self) -> None:
        """Release the underlying audio stream."""
        if self._closed:
            return
        if not self._aborted:
            self._guarded(self._stream.stop, 1.0)
        self._guarded(self._stream.close, 1.0)
        self._closed = True
