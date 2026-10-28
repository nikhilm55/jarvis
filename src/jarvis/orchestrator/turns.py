"""One turn: route a command to the fast path or the brain, speak the answer, log it (FRS 4.3)."""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from jarvis.activity import ActivityLog, Route, ToolCallRecord, TurnRecord
from jarvis.brain import BrainUnavailable
from jarvis.brain.failures import internal_response
from jarvis.config import Settings
from jarvis.confirm import Confirmer, HudAnswers
from jarvis.confirm.consent_question import ConsentQuestion
from jarvis.consent.manage import ConsentAdmin
from jarvis.consent.manage import parse as parse_manage
from jarvis.consent.manage import run as run_manage
from jarvis.consent.session import SessionGrants
from jarvis.contract import FinalResponse
from jarvis.desktop.client import DesktopClient
from jarvis.fastpath import FastPathDeclined, Intent, execute
from jarvis.log import get_logger
from jarvis.orchestrator.controlling import ControlIndicator
from jarvis.orchestrator.envelope import build_envelope, new_turn_id
from jarvis.orchestrator.hud import HudEvent, HudSink
from jarvis.orchestrator.ports import BrainPort
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy import Mode
from jarvis.policy.decision import TurnContext
from jarvis.policy.ports import Confirmer as PolicyConfirmer
from jarvis.policy.ports import ConsentBroker, NoConfirmer, NoConsent
from jarvis.stt import Transcript
from jarvis.tts import SpeechHandle

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
    clock: Callable[[], float] = time.monotonic  # injected by tests (FR-TALK-02 timing)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    consent: ConsentBroker = field(default_factory=NoConsent)
    grants: SessionGrants | None = None  # once grants end with the command (FR-CON-09)
    answers: HudAnswers | None = None  # HUD answers to confirmations; None: nothing confirms
    consent_admin: ConsentAdmin | None = None  # "Jarvis, allow Teams" and friends (FR-CON-13)


class TurnRunner:
    """Runs one command to completion, speaks the result and writes the activity record."""

    def __init__(self, services: TurnServices) -> None:
        """Bind the services used for the lifetime of the runner."""
        self._s = services
        self._hud = services.hud
        self._spoken = False
        self._thinking: SpeechHandle | None = None
        self._root: str | None = None  # the first turn of the command being run
        self._heard: list[str] = []  # the running turn's words from the user (R83)
        self._indicator = ControlIndicator(services.hud)
        self._told_cloud: set[str] = set()  # sources already told their data goes to Claude

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
        ctx = TurnContext(
            turn_id,
            self._s.settings.policy,
            self._s.mode,
            confirmer=self._confirmer(),
            consent=self._s.consent,
            controlling=self._indicator.driving,
            consent_question=self._consent_question(),
        )
        record.policy_decisions = ctx.policy_decisions  # the gate appends as it decides
        ctx.heard.extend(dict.fromkeys((command.raw, command.text)))  # R83: the user's own words
        self._heard = ctx.heard
        self._spoken = False
        self._thinking = None
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
        manage = parse_manage(command.text) if self._s.consent_admin is not None else None
        if manage is not None and self._s.consent_admin is not None:
            await self._hud(HudEvent("acting", command.text))
            return await run_manage(manage, self._s.consent_admin, ctx)
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

    def _confirmer(self) -> PolicyConfirmer:
        """The turn's confirmer; it speaks, so the thinking earcon stops first (FR-TALK-02)."""
        if self._s.answers is None:
            return NoConfirmer()
        return Confirmer(
            self._s.voice,
            self._s.windows,
            self._hud,
            self._s.answers,
            before_speaking=self._mark_spoken,
        )

    def _consent_question(self) -> ConsentQuestion | None:
        """The turn's consent question (FR-CON-04..07); without HUD answers wired, none."""
        if self._s.answers is None:
            return None
        return ConsentQuestion(
            self._s.voice,
            self._s.windows,
            self._hud,
            self._s.answers,
            told_cloud=self._told_cloud,
            before_speaking=self._mark_spoken,
        )

    def _mark_spoken(self) -> None:
        self._spoken = True
        self._cut_thinking()

    async def _on_say(self, text: str) -> None:
        """Speak a brain utterance and mirror it to the HUD."""
        self._spoken = True
        self._cut_thinking()
        await self._hud(HudEvent("speaking", text))
        self._s.voice.say(text)

    async def _on_ask(self, question: str, options: list[str]) -> str:
        """Ask the user a question and wait for their reply."""
        self._spoken = True
        self._cut_thinking()
        await self._hud(HudEvent("reply", question, {"options": options}))
        handle = self._s.voice.say(question)
        await self._s.voice.wait(handle)
        await self._hud(HudEvent("listening", "Reply...", {"window": "reply"}))
        seconds = self._s.timing.reply_window_s
        reply = await self._s.windows.ask(seconds)
        if reply is None:
            return f"(no reply from the user within {seconds:g} seconds)"
        self._heard.append(reply)  # the user's own words count for R83
        return reply

    async def _finish(self, final: FinalResponse) -> None:
        """Speak the final answer, update the HUD and wait for the audio."""
        self._spoken = True
        self._cut_thinking()
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
        """FR-TALK-02: at end of speech + 1.2 s, play the earcon if nothing was spoken yet."""
        due = speech_ended_at + self._s.timing.thinking_after_s - self._s.clock()
        await self._s.sleep(max(0.0, due))
        if not self._spoken:
            self._spoken = True
            self._thinking = self._s.voice.earcon("thinking")

    def _cut_thinking(self) -> None:
        """Stop the thinking earcon: a reply must never queue behind it (latency, task 13)."""
        handle, self._thinking = self._thinking, None
        if handle is not None:
            handle.cancel()
