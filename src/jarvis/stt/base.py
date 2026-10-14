"""Base abstractions for Jarvis speech-to-text."""

import io
import os
import re
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jarvis.audio.sources import SAMPLE_RATE, Pcm

__all__ = [
    "SttUnavailable",
    "Transcriber",
    "Transcript",
    "clean_transcript",
    "encode_wav",
    "find_server_bin",
]


class SttUnavailable(RuntimeError):
    """Raised when speech-to-text cannot run."""

    code = "STT_UNAVAILABLE"

    def __init__(self, reason: str, remedy: str) -> None:
        super().__init__(f"STT_UNAVAILABLE: {reason}. {remedy}")
        self.reason = reason
        self.remedy = remedy


@dataclass(frozen=True)
class Transcript:
    """Result of a speech-to-text call."""

    text: str
    engine: str
    seconds: float


class Transcriber(Protocol):
    """Protocol for speech-to-text engines."""

    def transcribe(self, pcm: Pcm, prompt: str | None = None) -> Transcript: ...


def encode_wav(pcm: Pcm) -> bytes:
    """Encode 16 kHz mono 16-bit PCM into an in-memory WAV."""
    if pcm.ndim != 1:
        raise ValueError("pcm must be 1-dimensional")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.astype("<i2").tobytes())
    return buf.getvalue()


_NON_SPEECH_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪")


def clean_transcript(raw: str) -> str:
    """Remove whisper.cpp non-speech markers and collapse whitespace."""
    cleaned = _NON_SPEECH_RE.sub("", raw)
    return " ".join(cleaned.split())


def find_server_bin(setting: str | None) -> Path:
    """Locate the whisper.cpp whisper-server executable."""
    if setting is not None and setting != "":
        candidate = Path(setting)
        if not candidate.is_file():
            raise SttUnavailable(
                reason=f"the whisper-server file {candidate} does not exist",
                remedy="Fix stt.server_bin in the config or JARVIS_WHISPER_SERVER",
            )
        return candidate
    env_val = os.environ.get("JARVIS_WHISPER_SERVER", "")
    if env_val != "":
        candidate = Path(env_val)
        if not candidate.is_file():
            raise SttUnavailable(
                reason=f"the whisper-server file {candidate} does not exist",
                remedy="Fix stt.server_bin in the config or JARVIS_WHISPER_SERVER",
            )
        return candidate
    found = shutil.which("whisper-server")
    if found is not None:
        return Path(found)
    raise SttUnavailable(
        reason="whisper-server is not installed",
        remedy=(
            "Build whisper.cpp and set stt.server_bin in the config, "
            "set JARVIS_WHISPER_SERVER, or put whisper-server on PATH"
        ),
    )
