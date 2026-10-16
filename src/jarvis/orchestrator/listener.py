"""What to do with a speech segment: wake rules, gate, windows, Stop (R21, R48-R51)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from jarvis.activity import ActivityLog, TurnRecord
from jarvis.config import Settings
from jarvis.fastpath import match
from jarvis.fastpath.intents import Stop
from jarvis.log import get_logger
from jarvis.orchestrator.envelope import new_turn_id
from jarvis.orchestrator.hud import HudEvent, HudSink
from jarvis.orchestrator.ports import TranscriberPort
from jarvis.orchestrator.segmenter import Segment
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.turns import Command
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.stt import Transcript
from jarvis.wake import gate

__all__ = ["NOT_UNDERSTOOD", "STT_DOWN", "WAKE_PROMPT", "Listener", "ListenerServices"]

logger = get_logger(__name__)

WAKE_PROMPT = "Jarvis, open Teams. Jarvis, what's on my calendar?"
NOT_UNDERSTOOD = "Sorry, I didn't catch that."
STT_DOWN = "Speech recognition isn't working right now."


@dataclass(frozen=True)
class ListenerServices:
    """Wiring for the listener: settings, ports, sinks, and callbacks."""

    settings: Settings
    transcriber: TranscriberPort
    voice: Voice
    windows: Windows
    hud: HudSink
    activity: ActivityLog
    timing: Timing
    submit: Callable[[Command], None]
    stop: Callable[[], Awaitable[None]]
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class Heard:
    """A successful transcription result with timing."""

    text: str
    transcript: Transcript
    stt_ms: int


class Listener:
    """Decides what to do with each finished speech segment."""

    def __init__(self, services: ListenerServices) -> None:
        """Store the services for later use."""
        self._s = services
        self._inflight: asyncio.Future[Transcript] | None = None

    async def drain(self, timeout: float) -> None:
        """Wait (up to `timeout`) for a transcription still running on its thread (R30)."""
        pending = self._inflight
        if pending is not None and not pending.done():
            await asyncio.wait({pending}, timeout=timeout)

    async def handle(self, segment: Segment) -> None:
        """Dispatch a segment by window kind, ignoring tainted audio."""
        s = self._s
        if segment.tainted:
            s.windows.release()  # the speech that held a window was not the user's
            return
        arrived = s.clock()
        kind = s.windows.kind
        if kind == "reply":
            try:
                await self._on_reply(segment)
            finally:
                s.windows.release()  # a held reply window must not stay held for good
        elif kind == "listen":
            await self._on_listen(segment, arrived)
        else:
            await self._on_wake(segment, arrived)

    async def _on_wake(self, segment: Segment, arrived: float) -> None:
        """Handle a segment in the wake window (R48)."""
        s = self._s
        if segment.wake_score < s.settings.wake.threshold:
            return
        if segment.silence_before_ms < s.timing.min_silence_ms:
            self._drop("", f"silence_before_ms<{s.timing.min_silence_ms}")
            return
        heard = await self._hear(segment, WAKE_PROMPT)
        if heard is None:
            return
        if heard.text == "":
            # Nothing was said after the wake: most likely a false wake, so end silently (B2).
            self._drop("", "empty transcript")
            return
        verdict = gate(heard.text)
        if not verdict.accepted:
            self._drop(heard.text, "gate rejected the first word")
            return
        await s.hud(HudEvent("transcript", heard.text))
        if verdict.command:
            await self._route(verdict.command, heard, arrived)
        else:
            await self._start_listening()

    async def _on_listen(self, segment: Segment, arrived: float) -> None:
        """Handle a segment inside an open listen window (R49)."""
        s = self._s
        s.windows.take_listen()
        heard = await self._hear(segment, None)
        if heard is None:
            return
        if heard.text == "":
            await self._not_understood("")
            return
        verdict = gate(heard.text)
        command = verdict.command if verdict.accepted else heard.text
        await s.hud(HudEvent("transcript", heard.text))
        if verdict.accepted and not command:
            await self._start_listening()
        else:
            await self._route(command, heard, arrived)

    async def _on_reply(self, segment: Segment) -> None:
        """Handle a segment while replying; detect Stop (R21)."""
        s = self._s
        heard = await self._hear(segment, None)
        if heard is None:
            return
        if heard.text == "":
            await self._not_understood("")
            return
        verdict = gate(heard.text)
        if verdict.accepted and isinstance(match(verdict.command), Stop):
            await s.hud(HudEvent("transcript", heard.text))
            await s.stop()
            return
        await s.hud(HudEvent("transcript", heard.text))
        s.windows.offer_answer(heard.text)

    async def _route(self, command: str, heard: Heard, arrived: float) -> None:
        """Route a command to the fast path or the turn worker."""
        s = self._s
        intent = match(command)
        if isinstance(intent, Stop):
            await s.stop()
            return
        s.submit(
            Command(
                command,
                heard.text,
                heard.transcript,
                intent,
                arrived - s.timing.trailing_s,
                heard.stt_ms,
            )
        )

    async def _transcribe(self, segment: Segment, prompt: str | None) -> Transcript:
        """Run the engine on a thread; it is shielded so shutdown can wait for it."""
        work = asyncio.ensure_future(
            asyncio.to_thread(self._s.transcriber.transcribe, segment.utterance.pcm, prompt)
        )
        work.add_done_callback(_ignore_result)
        self._inflight = work
        return await asyncio.shield(work)

    async def _hear(self, segment: Segment, prompt: str | None) -> Heard | None:
        """Transcribe the segment, degrading gracefully on engine failure."""
        s = self._s
        started = s.clock()
        try:
            transcript = await self._transcribe(segment, prompt)
        except Exception:
            logger.exception("transcription failed")
            await s.hud(HudEvent("error", "Speech recognition failed"))
            handle = s.voice.say(STT_DOWN)
            await s.voice.wait(handle)
            return None
        return Heard(
            transcript.text.strip(),
            transcript,
            int((s.clock() - started) * 1000),
        )

    async def _start_listening(self) -> None:
        """Open a listen window after a bare wake word."""
        s = self._s
        await s.hud(HudEvent("listening", "Listening...", {"window": "listen"}))
        handle = s.voice.earcon("wake")
        await s.voice.wait(handle)
        s.windows.open_listen(s.timing.listen_window_s, self._listen_timeout)

    async def _listen_timeout(self) -> None:
        """Close the listen window on timeout."""
        await self._s.hud(HudEvent("idle"))

    async def _not_understood(self, raw: str) -> None:
        """Apologise for an empty transcript where the user is waiting for an answer (R51)."""
        self._drop(raw, "empty transcript")
        s = self._s
        await s.hud(HudEvent("reply", NOT_UNDERSTOOD))
        handle = s.voice.say(NOT_UNDERSTOOD)
        await s.voice.wait(handle)
        await s.hud(HudEvent("idle"))

    def _drop(self, raw: str, reason: str) -> None:
        """Record a dropped turn in the activity log."""
        self._s.activity.record(
            TurnRecord(
                ts=datetime.now().astimezone(),
                turn_id=new_turn_id(),
                raw_transcript=raw,
                command="",
                route="dropped",
                drop_reason=reason,
            )
        )


def _ignore_result(work: asyncio.Future[Transcript]) -> None:
    """Mark a shielded transcription's outcome as seen, so an orphaned one does not warn."""
    if not work.cancelled():
        work.exception()
