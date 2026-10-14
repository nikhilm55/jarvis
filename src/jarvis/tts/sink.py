"""Audio output sink for the Jarvis TTS pipeline."""

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

    def __init__(self, sample_rate: int) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415
        except (ImportError, OSError) as error:
            raise AudioOutputError(f"sounddevice is unavailable: {error}") from error

        try:
            self._stream: Any = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                latency="low",
            )
            self._stream.start()
        except sd.PortAudioError as error:
            raise AudioOutputError(f"cannot open the audio output: {error}") from error

        self._aborted = False
        self._closed = False

    def write(self, block: Pcm) -> None:
        self._stream.write(block)

    def abort(self) -> None:
        self._stream.abort()
        self._aborted = True

    def close(self) -> None:
        if self._closed:
            return
        if not self._aborted:
            self._stream.stop()
        self._stream.close()
        self._closed = True
