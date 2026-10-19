"""One turn: route a command to the fast path or the brain, speak the answer, log it (FRS 4.3)."""

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime

from jarvis.activity import ActivityLog, Route, ToolCallRecord, TurnRecord
from jarvis.brain import BrainUnavailable
from jarvis.brain.failures import internal_response
from jarvis.config import Settings
from jarvis.consent.session import SessionGrants
from jarvis.contract import FinalResponse
from jarvis.desktop.client import DesktopClient
from jarvis.fastpath import FastPathDeclined, Intent, execute
from jarvis.log import get_logger
from jarvis.orchestrator.envelope import build_envelope, new_turn_id
from jarvis.orchestrator.hud import HudEvent, HudSink
from jarvis.orchestrator.ports import BrainPort
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy import Mode
from jarvis.policy.decision import TurnContext
from jarvis.policy.ports import ConsentBroker, NoConsent
from jarvis.stt import Transcript

logger = get_logger("turns")

__all__ = ["Command", "TurnRunner", "TurnServices"]


@dataclass(frozen=True)
class Command:
    """A single user command ready to be routed to the fast path or the brain."""

    text: str
    raw: str
    transcript: Transcript
    intent: Intent | None
    speech_ended_at: float
    stt_ms: int
    pending_question: str | None = None  # the question this command answers (R60)


@dataclass(frozen=True)
class TurnServices:
    """The collaborators a TurnRunner needs to complete one turn."""

    settings: Settings
    mode: Mode
    desktop: DesktopClient
    brain: BrainPort | None
    voice: Voice
    hud: HudSink
    activity: ActivityLog
    timing: Timing
    windows: Windows
    trace: ToolTrace
    consent: ConsentBroker = field(default_factory=NoConsent)
    grants: SessionGrants | None = None  # once grants end with the command (FR-CON-09)


class TurnRunner:
    """Runs one command to completion, speaks the result and writes the activity record."""

    def __init__(self, services: TurnServices) -> None:
        """Bind the services used for the lifetime of the runner."""
        self._s = services
        self._hud = services.hud
        self._spoken = False
        self._root: str | None = None  # the first turn of the command being run

    async def run(self, command: Command) -> None:
        """Run a command, then every follow-up answer its final response asks for (R60)."""
        current: Command | None = command
        self._root = None
        try:
            while current is not None:
                final = await self._turn(current)
                current = await self._follow_up(current, final)
        finally:
            if self._root is not None and self._s.grants is not None:
                self._s.grants.end_turn(self._root)  # a "once" grant ends with its command

    async def _follow_up(self, command: Command, final: FinalResponse) -> Command | None:
        """Open the reply window when the final expects an answer; the answer is a new command."""
        if not final.follow_up_expected or final.status == "failed":
            return None
        await self._hud(HudEvent("listening", "Reply...", {"window": "reply"}))
        answer = await self._s.windows.ask(self._s.timing.reply_window_s)
        if answer is None:
            await self._hud(HudEvent("idle"))
            return None
        transcript = Transcript(answer, command.transcript.engine, 0.0)
        return Command(answer, answer, transcript, None, time.monotonic(), 0, final.spoken)

    async def _turn(self, command: Command) -> FinalResponse:
        """Execute one turn: route, speak and log the outcome."""
        turn_id = new_turn_id()
        route: Route = "fastpath" if command.intent is not None else "brain"
        record = TurnRecord(
            ts=datetime.now().astimezone(),
            turn_id=turn_id,
            raw_transcript=command.raw,
            command=command.text,
            route=route,
        )
        record.durations_ms["stt"] = command.stt_ms
        if self._s.grants is not None:
            self._s.grants.start_turn(turn_id, follows=self._root)
        self._root = self._root or turn_id
        ctx = TurnContext(turn_id, self._s.settings.policy, self._s.mode, consent=self._s.consent)
        record.policy_decisions = ctx.policy_decisions  # the gate appends as it decides
        self._spoken = False
        started = time.monotonic()
        timer = asyncio.create_task(self._thinking_earcon(command.speech_ended_at))
        try:
            try:
                final = await self._route(command, record, ctx)
                record.final = final
                await self._finish(final)
            except asyncio.CancelledError:
                record.drop_reason = "cancelled"
                raise
            except Exception:
                logger.exception("turn failed", extra={"turn_id": turn_id})
                final = internal_response()
                record.final = final
                try:
                    await self._finish(final)
                except Exception:
                    logger.exception("finish failed", extra={"turn_id": turn_id})
        finally:
            record.durations_ms["total"] = int((time.monotonic() - started) * 1000)
            record.tool_calls.extend(self._s.trace.take())
            self._s.activity.record(record)
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timer
        return final

    async def _route(self, command: Command, record: TurnRecord, ctx: TurnContext) -> FinalResponse:
        """Send the command to the fast path when possible, otherwise to the brain."""
        if command.intent is not None:
            await self._hud(HudEvent("acting", command.text))
            try:
                final = await execute(command.intent, self._s.desktop, self._s.mode, ctx=ctx)
            except FastPathDeclined as declined:
                logger.info(
                    "fast path declined",
                    extra={"turn_id": ctx.turn_id, "reason": declined.reason},
                )
            else:
                record.tool_calls = [
                    ToolCallRecord(a.tool, {"summary": a.summary}) for a in final.actions_taken
                ]
                return final
        record.route = "brain"
        return await self._brain(command, record, ctx)

    async def _brain(self, command: Command, record: TurnRecord, ctx: TurnContext) -> FinalResponse:
        """Delegate the command to the brain, or report that it is unavailable."""
        if self._s.brain is None:
            return BrainUnavailable(
                "the brain is switched off for this run",
                ["Start Jarvis without --no-brain."],
            ).to_response()
        await self._hud(HudEvent("thinking", command.text))
        record.brain_model = self._s.settings.brain.model
        envelope = build_envelope(
            command=command.text,
            raw_transcript=command.raw,
            transcript=command.transcript,
            settings=self._s.settings,
            mode=self._s.mode,
            turn_id=ctx.turn_id,
            pending_question=command.pending_question,
        )
        self._s.trace.take()
        self._s.trace.ctx = ctx  # the MCP server judges the brain's tool calls in this turn
        t0 = time.monotonic()
        try:
            return await self._s.brain.turn(envelope, self._on_say, self._on_ask)
        finally:
            record.durations_ms["brain"] = int((time.monotonic() - t0) * 1000)

    async def _on_say(self, text: str) -> None:
        """Speak a brain utterance and mirror it to the HUD."""
        self._spoken = True
        await self._hud(HudEvent("speaking", text))
        self._s.voice.say(text)

    async def _on_ask(self, question: str, options: list[str]) -> str:
        """Ask the user a question and wait for their reply."""
        self._spoken = True
        await self._hud(HudEvent("reply", question, {"options": options}))
        handle = self._s.voice.say(question)
        await self._s.voice.wait(handle)
        await self._hud(HudEvent("listening", "Reply...", {"window": "reply"}))
        seconds = self._s.timing.reply_window_s
        reply = await self._s.windows.ask(seconds)
        return f"(no reply from the user within {seconds:g} seconds)" if reply is None else reply

    async def _finish(self, final: FinalResponse) -> None:
        """Speak the final answer, update the HUD and wait for the audio."""
        self._spoken = True
        if final.status == "failed" and final.error is not None:
            await self._hud(HudEvent("error", final.error.what))
        display = final.display.model_dump(mode="json") if final.display is not None else None
        await self._hud(
            HudEvent("reply", final.spoken, {"status": final.status, "display": display})
        )
        spoken = final.spoken.strip()
        if spoken:
            await self._hud(HudEvent("speaking", final.spoken))
            handle = self._s.voice.say(final.spoken)
        else:
            handle = self._s.voice.earcon("error" if final.status == "failed" else "done")
        await self._s.voice.wait(handle)
        await self._hud(HudEvent("idle"))

    async def _thinking_earcon(self, speech_ended_at: float) -> None:
        """Play the thinking earcon if the user has not been spoken to yet."""
        delay = max(0.0, speech_ended_at + self._s.timing.thinking_after_s - time.monotonic())
        await asyncio.sleep(delay)
        if not self._spoken:
            self._spoken = True
            self._s.voice.earcon("thinking")
