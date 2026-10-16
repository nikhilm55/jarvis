"""Fast-path executor for deterministic, policy-gated desktop intents."""

import dataclasses
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import cast

from jarvis import policy
from jarvis.contract import FinalResponse
from jarvis.desktop.client import DesktopClient, DesktopError
from jarvis.fastpath import responses
from jarvis.fastpath.intents import (
    CloseApp,
    Intent,
    Mute,
    OpenApp,
    Stop,
    TellDate,
    TellTime,
    VolumeSet,
    VolumeStep,
)
from jarvis.policy.decision import ToolCall, ToolImpl, TurnContext
from jarvis.policy.gated import gated_dispatch, tool_impl

policy.register(policy.ToolSpec("clock.time", policy.Tier.T0))
policy.register(policy.ToolSpec("clock.date", policy.Tier.T0))

__all__ = ["FastPathDeclined", "execute"]


class FastPathDeclined(Exception):
    """The fast path declines; the orchestrator sends the command to the brain (FR-NLU-02)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _local_now() -> datetime:
    """Return the current local time as an aware datetime."""
    return datetime.now().astimezone()


def _tool_call(intent: Intent) -> tuple[str, dict[str, object]]:
    """Map an intent to its tool name and argument mapping."""
    tool: str
    args: dict[str, object]
    match intent:
        case OpenApp():
            tool = "desktop.open_app"
            args = {"query": intent.name}
        case CloseApp():
            tool = "desktop.close_app"
            args = {"query": intent.name}
        case TellTime():
            tool = "clock.time"
            args = {}
        case TellDate():
            tool = "clock.date"
            args = {}
        case VolumeSet():
            tool = "desktop.volume_set"
            args = {"pct": intent.percent}
        case VolumeStep():
            tool = "desktop.volume_step"
            args = {"delta": intent.delta}
        case Mute():
            tool = "desktop.mute"
            args = {"on": intent.on}
        case _:
            raise ValueError(f"Unsupported intent: {intent!r}")
    return tool, args


def _action(intent: Intent) -> str:
    """Return a short verb phrase describing the intent."""
    if isinstance(intent, OpenApp):
        return f"open {intent.name}"
    if isinstance(intent, CloseApp):
        return f"close {intent.name}"
    if isinstance(intent, (VolumeSet, VolumeStep)):
        return "change the volume"
    if isinstance(intent, Mute):
        return "mute" if intent.on else "unmute"
    return "do that"


def _impls(desktop: DesktopClient, clock: Callable[[], datetime]) -> dict[str, ToolImpl]:
    """The fast path's tool implementations; only `gated_dispatch` may call them."""

    @tool_impl
    async def open_app(args: Mapping[str, object]) -> object:
        return await desktop.open_app(cast(str, args["query"]))

    @tool_impl
    async def close_app(args: Mapping[str, object]) -> object:
        return await desktop.close_app(cast(str, args["query"]))

    @tool_impl
    async def volume_set(args: Mapping[str, object]) -> object:
        return await desktop.volume_set(cast(int, args["pct"]))

    @tool_impl
    async def volume_step(args: Mapping[str, object]) -> object:
        return await desktop.volume_step(cast(int, args["delta"]))

    @tool_impl
    async def mute(args: Mapping[str, object]) -> object:
        return await desktop.mute(cast(bool, args["on"]))

    @tool_impl
    async def now(args: Mapping[str, object]) -> object:
        return clock()

    return {
        "desktop.open_app": open_app,
        "desktop.close_app": close_app,
        "desktop.volume_set": volume_set,
        "desktop.volume_step": volume_step,
        "desktop.mute": mute,
        "clock.time": now,
        "clock.date": now,
    }


def _respond_app(intent: OpenApp | CloseApp, result: Mapping[str, object]) -> FinalResponse:
    app = responses.text_of(result, "app", intent.name)
    if isinstance(intent, OpenApp):
        return responses.ok(f"Opening {app}.", "desktop.open_app", f"Opened {app}", undoable=False)
    if result.get("closed") == 0:
        return responses.ok(f"{app} isn't open.", None)
    return responses.ok(f"Closed {app}.", "desktop.close_app", f"Closed {app}", undoable=False)


def _respond_clock(intent: TellTime | TellDate, now: object) -> FinalResponse:
    if not isinstance(now, datetime):
        raise ValueError("the clock tool returned no time")
    if isinstance(intent, TellTime):
        spoken = responses.spoken_time(now)
        return responses.ok(spoken, "clock.time", "Read the local time", undoable=False)
    return responses.ok(responses.spoken_date(now), "clock.date", "Read the local date")


def _respond_volume(
    intent: VolumeSet | VolumeStep | Mute, result: Mapping[str, object]
) -> FinalResponse:
    if isinstance(intent, VolumeSet):
        pct = responses.percent_of(result, intent.percent)
        summary = f"Set the volume to {pct} percent"
        return responses.ok(f"Volume {pct} percent.", "desktop.volume_set", summary, undoable=True)
    if isinstance(intent, VolumeStep):
        step_pct = responses.percent_of(result, None)
        spoken = "Volume changed." if step_pct is None else f"Volume {step_pct} percent."
        return responses.ok(spoken, "desktop.volume_step", "Changed the volume", undoable=True)
    word = "Muted" if intent.on else "Unmuted"
    return responses.ok(f"{word}.", "desktop.mute", word, undoable=True)


def _respond(intent: Intent, output: object) -> FinalResponse:
    """Build the spoken response for an intent whose tool ran."""
    result = cast("Mapping[str, object]", output) if isinstance(output, Mapping) else {}
    if isinstance(intent, (OpenApp, CloseApp)):
        return _respond_app(intent, result)
    if isinstance(intent, (TellTime, TellDate)):
        return _respond_clock(intent, output)
    if isinstance(intent, (VolumeSet, VolumeStep, Mute)):
        return _respond_volume(intent, result)
    raise ValueError(f"Unsupported intent: {intent!r}")


async def execute(
    intent: Intent,
    desktop: DesktopClient,
    mode: policy.Mode,
    *,
    clock: Callable[[], datetime] | None = None,
    ctx: TurnContext | None = None,
) -> FinalResponse:
    """Execute a fast-path intent through `gated_dispatch`, which gates, audits and runs it."""
    if isinstance(intent, Stop):
        raise ValueError("Stop is handled by the orchestrator, not executed")
    tool, args = _tool_call(intent)
    base = ctx or TurnContext("fastpath")
    turn = dataclasses.replace(base, mode=mode, impls=_impls(desktop, clock or _local_now))
    try:
        result = await gated_dispatch(ToolCall(tool, args, "fastpath"), turn)
        if result.error is not None:
            return responses.blocked(result.error.why, mode)
        return _respond(intent, result.output)
    except DesktopError as exc:
        if isinstance(intent, (OpenApp, CloseApp)) and exc.code in (
            "NOT_FOUND",
            "AMBIGUOUS",
        ):
            raise FastPathDeclined(f"{exc.code}: {exc.message}") from exc
        return responses.desktop_failure(_action(intent), exc)
