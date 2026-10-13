"""A whole Orchestrator wired to doubles: a pushed-segment feed, recording children."""

import json
from pathlib import Path
from typing import Any

from jarvis.activity import ActivityLog
from jarvis.config import Settings
from jarvis.orchestrator.components import Components
from jarvis.orchestrator.core import Orchestrator
from jarvis.orchestrator.hud import HudEvent
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.voice import Voice
from tests.core_feed import Feed
from tests.recording_rig import (
    RecordingBrain,
    RecordingDesktop,
    RecordingService,
    RecordingSpeaker,
    RecordingTranscriber,
)


class CoreRig:
    """The Orchestrator plus every double; `events` is the shared lifecycle log."""

    def __init__(
        self,
        tmp_path: Path,
        texts: list[str | Exception],
        *,
        with_brain: bool = True,
        timing: Timing | None = None,
    ) -> None:
        self.events: list[str] = []
        self.feed = Feed()
        self.speaker = RecordingSpeaker(self.events)
        self.transcriber = RecordingTranscriber(texts, self.events)
        self.desktop = RecordingDesktop(self.events)
        self.brain = RecordingBrain(self.events) if with_brain else None
        self.hud_events: list[HudEvent] = []
        self.activity_dir = tmp_path / "activity"
        the_timing = timing or Timing(deaf_tail_s=0.0)
        self.parts = parts = Components(
            source=self.feed,
            segmenter=self.feed,
            transcriber=self.transcriber,
            speaker=self.speaker,
            voice=Voice(self.speaker, the_timing),
            desktop=self.desktop,
            brain=self.brain,
            services=[RecordingService(self.events)],
        )
        self.orchestrator = Orchestrator(
            Settings(),
            parts,
            hud=self._hud,
            activity=ActivityLog(directory=self.activity_dir),
            timing=the_timing,
        )

    async def _hud(self, event: HudEvent) -> None:
        self.hud_events.append(event)

    @property
    def states(self) -> list[str]:
        return [event.state for event in self.hud_events]

    def records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.activity_dir.glob("*.jsonl")):
            records.extend(json.loads(x) for x in path.read_text(encoding="utf-8").splitlines())
        return records
