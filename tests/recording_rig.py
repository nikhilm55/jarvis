"""Recording doubles for the children the orchestrator starts and closes."""

import asyncio
import threading

from jarvis.audio.sources import Pcm
from jarvis.contract import FinalResponse
from jarvis.stt import Transcript
from tests.fastpath_fakes import FakeDesktop
from tests.listener_rig import FakeTranscriber
from tests.orchestrator_rig import FakeBrain, FakeSpeaker


class RecordingTranscriber(FakeTranscriber):
    """Logs start and close into the shared event list; `fail_start` makes start() raise."""

    def __init__(self, texts: list[str | Exception], events: list[str]) -> None:
        super().__init__(texts)
        self.events = events
        self.fail_start: Exception | None = None
        self.gate: threading.Event | None = None  # when set, transcribe() blocks on it

    def transcribe(self, pcm: Pcm, prompt: str | None = None) -> Transcript:
        self.events.append("transcribe.start")
        if self.gate is not None:
            self.gate.wait(5)
        try:
            return super().transcribe(pcm, prompt)
        finally:
            self.events.append("transcribe.end")

    def start(self) -> None:
        self.events.append("transcriber.start")
        if self.fail_start is not None:
            raise self.fail_start

    def close(self) -> None:
        self.events.append("transcriber.close")


class RecordingSpeaker(FakeSpeaker):
    """A FakeSpeaker that logs close()."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def close(self) -> None:
        self.events.append("speaker.close")


class RecordingDesktop(FakeDesktop):
    """A FakeDesktop that logs close()."""

    def __init__(self, events: list[str]) -> None:
        super().__init__([])
        self.log = events

    async def close(self) -> None:
        self.log.append("desktop.close")
        await super().close()


class RecordingBrain(FakeBrain):
    """A FakeBrain that logs its lifecycle; `reset_called` is set by reset()."""

    def __init__(
        self,
        events: list[str],
        final: FinalResponse | None = None,
        finals: list[FinalResponse] | None = None,
    ) -> None:
        super().__init__(final, finals=finals)
        self.events = events
        self.reset_called = asyncio.Event()
        self.fail_start: Exception | None = None

    async def start(self) -> None:
        self.events.append("brain.start")
        if self.fail_start is not None:
            raise self.fail_start

    async def reset(self) -> None:
        self.events.append("brain.reset")
        self.reset_called.set()

    async def close(self) -> None:
        self.events.append("brain.close")


class RecordingService:
    """A ServicePort (stands in for the MCP server) that logs start and close."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("service.start")

    async def close(self) -> None:
        self.events.append("service.close")
