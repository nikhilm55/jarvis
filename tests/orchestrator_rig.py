"""Doubles and a rig for the TurnRunner tests: fake speaker, brain, desktop and HUD."""

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jarvis.activity import ActivityLog
from jarvis.brain.dispatch import OnAsk, OnSay
from jarvis.config import Settings
from jarvis.contract import FinalResponse, TurnEnvelope
from jarvis.desktop.client import DesktopError
from jarvis.fastpath.intents import Intent
from jarvis.orchestrator.hud import HudEvent
from jarvis.orchestrator.ports import BrainPort
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.turns import Command, TurnRunner, TurnServices
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.stt import Transcript
from jarvis.tts import SpeechHandle
from tests.fastpath_fakes import FakeDesktop


class FakeSpeaker:
    """Records what is spoken and finishes every handle at once."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.earcons: list[str] = []

    def say(self, text: str) -> SpeechHandle:
        self.said.append(text)
        return self._ended(text)

    def earcon(self, name: str) -> SpeechHandle:
        self.earcons.append(name)
        return self._ended(name)

    def close(self) -> None:
        return None

    @staticmethod
    def _ended(label: str) -> SpeechHandle:
        handle = SpeechHandle(label, time.monotonic)
        handle._finish()
        return handle


class FakeBrain:
    """A BrainPort whose turn can be held open, made to fail, or answered at once."""

    def __init__(self, final: FinalResponse | None = None) -> None:
        self.final = final or FinalResponse(status="success", spoken="Handled by the brain.")
        self.envelopes: list[TurnEnvelope] = []
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.error: Exception | None = None

    async def start(self) -> None:
        return None

    async def reset(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def dispatch(self, policy_name: str, args: dict[str, object]) -> object:
        return "ok"

    async def turn(self, envelope: TurnEnvelope, on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
        self.envelopes.append(envelope)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.final


class Rig:
    """A TurnRunner plus every double it talks to."""

    def __init__(
        self,
        tmp_path: Path,
        brain: BrainPort | None,
        timing: Timing,
        error: DesktopError | None,
    ) -> None:
        self.speaker = FakeSpeaker()
        self.hud_events: list[HudEvent] = []
        self.desktop_events: list[str] = []
        self.windows = Windows()
        self.tmp_path = tmp_path
        services = TurnServices(
            settings=Settings(),
            mode="balanced",
            desktop=FakeDesktop(self.desktop_events, error=error),
            brain=brain,
            voice=Voice(self.speaker, timing),
            hud=self._hud,
            activity=ActivityLog(directory=tmp_path),
            timing=timing,
            windows=self.windows,
            trace=ToolTrace(),
        )
        self.runner = TurnRunner(services)

    async def _hud(self, event: HudEvent) -> None:
        self.hud_events.append(event)

    @property
    def states(self) -> list[str]:
        return [event.state for event in self.hud_events]

    def records(self) -> list[dict[str, Any]]:
        path = next(self.tmp_path.glob("*.jsonl"))
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]


def make_rig(
    tmp_path: Path,
    brain: BrainPort | None = None,
    timing: Timing | None = None,
    error: DesktopError | None = None,
) -> Rig:
    return Rig(tmp_path, brain, timing or Timing(deaf_tail_s=0.0), error)


def command(text: str, intent: Intent | None, *, ended_ago: float = 0.0) -> Command:
    raw = f"Jarvis, {text}"
    transcript = Transcript(raw, "whisper.cpp/tiny.en", 0.1)
    return Command(text, raw, transcript, intent, time.monotonic() - ended_ago, 120)


async def until(condition: Callable[[], bool]) -> None:
    async def spin() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(spin(), 2)
