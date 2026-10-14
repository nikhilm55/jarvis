"""The narrow interfaces the orchestrator needs, so tests can inject fakes for every component."""

from typing import Protocol

from jarvis.audio.sources import Pcm
from jarvis.brain.dispatch import OnAsk, OnSay
from jarvis.contract import FinalResponse, TurnEnvelope
from jarvis.orchestrator.segmenter import Segment, SegmentEvent
from jarvis.stt import Transcript
from jarvis.tts import SpeechHandle

__all__ = [
    "BrainPort",
    "SegmenterPort",
    "ServicePort",
    "SpeakerPort",
    "TranscriberPort",
]


class SpeakerPort(Protocol):
    """Interface for text-to-speech output and earcon playback."""

    def say(self, text: str) -> SpeechHandle: ...

    def earcon(self, name: str) -> SpeechHandle: ...

    def close(self) -> None: ...


class TranscriberPort(Protocol):
    """Interface for speech-to-text transcription of PCM audio."""

    def transcribe(self, pcm: Pcm, prompt: str | None = None) -> Transcript: ...

    def start(self) -> None: ...

    def close(self) -> None: ...


class BrainPort(Protocol):
    """Interface for the conversational brain that processes turns and dispatches policies."""

    async def start(self) -> None: ...

    async def turn(self, envelope: TurnEnvelope, on_say: OnSay, on_ask: OnAsk) -> FinalResponse: ...

    async def dispatch(self, policy_name: str, args: dict[str, object]) -> object: ...

    async def reset(self) -> None: ...

    async def close(self) -> None: ...


class ServicePort(Protocol):
    """Interface for a background service that can be started and closed."""

    async def start(self) -> None: ...

    async def close(self) -> None: ...


class SegmenterPort(Protocol):
    """Interface for segmenting a PCM stream into discrete speech segments."""

    def feed(self, frame: Pcm) -> list[SegmentEvent]: ...

    def flush(self) -> list[Segment]: ...
