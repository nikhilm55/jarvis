"""The pieces of the M1 acceptance run that feed speech and judge what happened."""

import asyncio
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from acceptance_audio import (
    Playback,
    PlaybackLog,
    QueueSource,
)
from acceptance_report import (
    Row,
    row_from_record,
)

from jarvis.activity import ActivityLog, TurnRecord
from jarvis.audio.sources import SAMPLE_RATE, Pcm
from jarvis.brain import BrainUnavailable
from jarvis.brain.dispatch import OnAsk, OnSay
from jarvis.contract import FinalResponse, TurnEnvelope
from jarvis.desktop.x11 import WindowInfo, list_windows
from jarvis.orchestrator.hud import HudEvent
from jarvis.orchestrator.ports import BrainPort

MAX_BRAIN_TURNS = 5  # the most live Claude Code turns one run may use
FIRST_WORD_DROP = "gate rejected the first word"
CALCULATOR_CLASSES = frozenset({"gnome-calculator", "org.gnome.calculator"})
NO_LATENCY: dict[str, Any] = {
    "eos_to_audio_ms": None,
    "eos_to_speech_ms": None,
    "action_ms": None,
}
FAST_TIMEOUT_S = 30.0
BRAIN_TIMEOUT_S = 180.0
EOS_SETTLE_S = 8.0  # how long "nothing happens" is watched for after speech ends


def is_calculator(window: WindowInfo) -> bool:
    """True for a GNOME Calculator window; LibreOffice Calc and the like must not match."""
    return (
        window.wm_class.lower() in CALCULATOR_CLASSES
        or window.wm_instance.lower() in CALCULATOR_CLASSES
    )


def calculator_windows() -> list[WindowInfo]:
    """The Calculator windows on the desktop right now."""
    return [w for w in list_windows() if is_calculator(w)]


def load_wav(path: Path) -> Pcm:
    """Read a 16 kHz mono 16-bit fixture."""
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ValueError(f"{path}: not a 16 kHz mono 16-bit WAV")
        raw = wav.readframes(wav.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.int16)


def judge(expected_route: str, record: TurnRecord | None, problem: str | None) -> str:
    """PASS, or FAIL with the first thing that was wrong."""
    if record is None:
        return "FAIL: no turn happened"
    if record.route != expected_route:
        return f"FAIL: route was {record.route}, expected {expected_route}"
    if record.final is None or record.final.status == "failed":
        return "FAIL: the turn failed"
    if problem:
        return f"FAIL: {problem}"
    return "PASS"


def judge_dropped(ran: bool, calculator_open: bool, records: list[TurnRecord]) -> str | None:
    """None when the utterance was heard and dropped by the first-word rule, else the problem."""
    if ran:
        return "a turn ran"
    if calculator_open:
        return "Calculator opened"
    dropped = [r for r in records if r.route == "dropped"]
    if not dropped:
        return "nothing was dropped, so the utterance was never heard"
    if dropped[-1].drop_reason != FIRST_WORD_DROP:
        return f"dropped for {dropped[-1].drop_reason!r}, not the first-word rule"
    return None


class BrainGate:
    """The real brain behind a switch and a cap: only the brain cases get a live turn."""

    def __init__(self, inner: BrainPort, limit: int = MAX_BRAIN_TURNS) -> None:
        self._inner = inner
        self._limit = limit
        self.open = False
        self.turns = 0
        self.refused = 0

    async def start(self) -> None:
        await self._inner.start()

    async def turn(self, envelope: TurnEnvelope, on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
        if not self.open or self.turns >= self._limit:
            self.refused += 1
            return BrainUnavailable(
                "the acceptance run allows no live brain turn here",
                ["Only the brain cases, and at most five turns, may use Claude Code."],
            ).to_response()
        self.turns += 1
        return await self._inner.turn(envelope, on_say, on_ask)

    async def dispatch(self, policy_name: str, args: dict[str, object]) -> object:
        return await self._inner.dispatch(policy_name, args)

    async def reset(self) -> None:
        await self._inner.reset()

    async def close(self) -> None:
        await self._inner.close()


def ms_between(start: float, playback: Playback | None) -> int | None:
    """Milliseconds from `start` to a playback's first sound."""
    return None if playback is None else round((playback.at - start) * 1000)


class CapturingLog(ActivityLog):
    """The real activity log (written under the scratch home) that also keeps the records."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[TurnRecord] = []

    def record(self, record: TurnRecord) -> None:
        self.records.append(record)
        super().record(record)

    def turns(self) -> list[TurnRecord]:
        """Records of turns that ran (not the dropped ones)."""
        return [r for r in self.records if r.route != "dropped"]


@dataclass
class Harness:
    """Everything the scenario needs to feed speech and watch what comes back."""

    source: QueueSource
    log: CapturingLog
    playback: PlaybackLog
    manifest: dict[str, dict[str, Any]]
    fixtures: Path
    hud: list[tuple[float, HudEvent]] = field(default_factory=list)
    exec_ms: list[int] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    earcon_first: list[str] = field(default_factory=list)

    async def say(self, name: str) -> float:
        """Feed a fixture; return the clock time its speech ends."""
        pcm = load_wav(self.fixtures / f"{name}.wav")
        start = await asyncio.to_thread(self.source.feed, pcm)
        return start + float(self.manifest[name]["speech_end_s"])

    async def until(self, ready: Callable[[], bool], timeout: float) -> bool:
        """Poll `ready` (off the loop) until it is true or `timeout` passes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await asyncio.to_thread(ready):
                return True
            await asyncio.sleep(0.1)
        return False

    async def new_turn(self, seen: int, timeout: float) -> TurnRecord | None:
        """The next turn record after `seen` turns, or None on timeout."""
        found = await self.until(lambda: len(self.log.turns()) > seen, timeout)
        return self.log.turns()[seen] if found else None

    async def hud_event(self, state: str, after: int, timeout: float) -> bool:
        """Wait for a HUD event of `state` after the first `after` events."""
        return await self.until(lambda: any(e.state == state for _, e in self.hud[after:]), timeout)

    def add(self, case: str, run: int, record: TurnRecord | None, outcome: str, eos: float) -> None:
        """Add a result row with its latencies."""
        any_sound = self.playback.first_after(eos)
        speech = self.playback.first_after(eos, speech_only=True)
        action = None
        if record is not None and record.route == "brain":
            action = record.durations_ms.get("brain")
        elif record is not None and record.route == "fastpath" and self.exec_ms:
            action = self.exec_ms[-1]
        if any_sound is not None and any_sound.is_earcon:
            self.earcon_first.append(f"{case} #{run}")
        self.rows.append(
            row_from_record(
                case,
                run,
                record,
                outcome=outcome,
                eos_to_audio_ms=ms_between(eos, any_sound),
                eos_to_speech_ms=ms_between(eos, speech),
                action_ms=action,
            )
        )


async def turn_case(  # noqa: PLR0913, PLR0917 - a case is exactly these parts
    h: Harness,
    case: str,
    run: int,
    fixture: str,
    route: str,
    check: Callable[[TurnRecord], Awaitable[str | None]],
) -> None:
    """Say one command, wait for its turn, check the effect, record the row."""
    seen = len(h.log.turns())
    if route == "brain" and sum(r.route == "brain" for r in h.log.turns()) >= MAX_BRAIN_TURNS:
        outcome = f"FAIL: skipped, {MAX_BRAIN_TURNS} live brain turns already used"
        h.rows.append(row_from_record(case, run, None, outcome=outcome, **NO_LATENCY))
        return
    eos = await h.say(fixture)
    record = await h.new_turn(seen, BRAIN_TIMEOUT_S if route == "brain" else FAST_TIMEOUT_S)
    problem = await check(record) if record is not None else None
    h.add(case, run, record, judge(route, record, problem), eos)


async def calc_is(want_open: bool, h: Harness) -> str | None:
    """None when Calculator reaches the wanted state, else a description of the problem."""
    ok = await h.until(lambda: bool(calculator_windows()) == want_open, 6.0)
    return None if ok else f"Calculator did not {'appear' if want_open else 'close'}"
