"""Doubles and a rig for the Listener tests: scripted transcriber, speaker, HUD and clock."""

import json
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.activity import ActivityLog
from jarvis.audio import FRAME_SAMPLES, Utterance
from jarvis.audio.sources import Pcm
from jarvis.config import Settings
from jarvis.orchestrator.hud import HudEvent
from jarvis.orchestrator.listener import Listener, ListenerServices
from jarvis.orchestrator.segmenter import Segment
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.turns import Command
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.stt import Transcript
from tests.orchestrator_rig import FakeSpeaker


class FakeTranscriber:
    """Returns the scripted texts in order; an Exception in the script is raised instead."""

    def __init__(self, texts: list[str | Exception]) -> None:
        self.texts = list(texts)
        self.prompts: list[str | None] = []

    def transcribe(self, pcm: Pcm, prompt: str | None = None) -> Transcript:
        self.prompts.append(prompt)
        item = self.texts.pop(0)
        if isinstance(item, Exception):
            raise item
        return Transcript(item, "whisper.cpp/tiny.en", 0.1)

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeClock:
    """A settable monotonic clock."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def seg(score: float = 0.5, silence_ms: int = 800, *, tainted: bool = False) -> Segment:
    """A finished segment; the default score clears the wake threshold (0.005)."""
    pcm = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    return Segment(Utterance(pcm, 0.0, 1.0), silence_ms, score, tainted)


class ListenerRig:
    """A Listener wired to doubles; `submitted` and `stops` show what it decided."""

    def __init__(self, tmp_path: Path, texts: list[str | Exception], timing: Timing) -> None:
        self.speaker = FakeSpeaker()
        self.transcriber = FakeTranscriber(texts)
        self.windows = Windows()
        self.clock = FakeClock()
        self.hud_events: list[HudEvent] = []
        self.submitted: list[Command] = []
        self.stops = 0
        self.tmp_path = tmp_path
        self.listener = Listener(
            ListenerServices(
                settings=Settings(),
                transcriber=self.transcriber,
                voice=Voice(self.speaker, timing),
                windows=self.windows,
                hud=self._hud,
                activity=ActivityLog(directory=tmp_path),
                timing=timing,
                submit=self.submitted.append,
                stop=self._stop,
                clock=self.clock,
            )
        )

    async def _hud(self, event: HudEvent) -> None:
        self.hud_events.append(event)

    async def _stop(self) -> None:
        self.stops += 1

    @property
    def states(self) -> list[str]:
        return [event.state for event in self.hud_events]

    def records(self) -> list[dict[str, Any]]:
        files = list(self.tmp_path.glob("*.jsonl"))
        if not files:
            return []
        lines = files[0].read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]


def make_listener_rig(
    tmp_path: Path, texts: list[str | Exception], timing: Timing | None = None
) -> ListenerRig:
    return ListenerRig(tmp_path, texts, timing or Timing(deaf_tail_s=0.0))
