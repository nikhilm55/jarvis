"""Fast-path executor for deterministic, policy-gated desktop intents."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime

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


async def _gated(
    gate_fn: Callable[[str, Mapping[str, object], policy.Mode], policy.Decision],
    tool: str,
    args: Mapping[str, object],
    mode: policy.Mode,
) -> policy.Decision:
    """Run the policy gate in a worker thread, failing closed on any error."""
    try:
        return await asyncio.to_thread(gate_fn, tool, args, mode)
    except Exception:
        return policy.Decision(False, "policy error")


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


async def _run_app(intent: OpenApp, desktop: DesktopClient) -> FinalResponse:
    """Open an app and report the result."""
    result = await desktop.open_app(intent.name)
    app = responses.text_of(result, "app", intent.name)
    return responses.ok(
        f"Opening {app}.",
        "desktop.open_app",
        f"Opened {app}",
        undoable=False,
    )


async def _run_close(intent: CloseApp, desktop: DesktopClient) -> FinalResponse:
    """Close an app and report the result."""
    result = await desktop.close_app(intent.name)
    app = responses.text_of(result, "app", intent.name)
    if result.get("closed") == 0:
        return responses.ok(f"{app} isn't open.", None)
    return responses.ok(
        f"Closed {app}.",
        "desktop.close_app",
        f"Closed {app}",
        undoable=False,
    )


def _run_clock(intent: TellTime | TellDate, clock: Callable[[], datetime]) -> FinalResponse:
    """Read the local time or date and report it."""
    now = clock()
    if isinstance(intent, TellTime):
        spoken = responses.spoken_time(now)
        return responses.ok(spoken, "clock.time", "Read the local time", undoable=False)
    spoken = responses.spoken_date(now)
    return responses.ok(spoken, "clock.date", "Read the local date", undoable=False)


async def _run_volume(
    intent: VolumeSet | VolumeStep | Mute, desktop: DesktopClient
) -> FinalResponse:
    """Adjust the volume or mute state and report it."""
    if isinstance(intent, VolumeSet):
        result = await desktop.volume_set(intent.percent)
        pct = responses.percent_of(result, intent.percent)
        return responses.ok(
            f"Volume {pct} percent.",
            "desktop.volume_set",
            f"Set the volume to {pct} percent",
            undoable=True,
        )
    if isinstance(intent, VolumeStep):
        result = await desktop.volume_step(intent.delta)
        pct = responses.percent_of(result, 0)
        return responses.ok(
            f"Volume {pct} percent.",
            "desktop.volume_step",
            "Changed the volume",
            undoable=True,
        )
    await desktop.mute(intent.on)
    word = "Muted" if intent.on else "Unmuted"
    return responses.ok(f"{word}.", "desktop.mute", word, undoable=True)


async def _run(
    intent: Intent, desktop: DesktopClient, clock: Callable[[], datetime]
) -> FinalResponse:
    """Dispatch an allowed intent to the appropriate handler."""
    if isinstance(intent, OpenApp):
        return await _run_app(intent, desktop)
    if isinstance(intent, CloseApp):
        return await _run_close(intent, desktop)
    if isinstance(intent, (TellTime, TellDate)):
        return _run_clock(intent, clock)
    if isinstance(intent, (VolumeSet, VolumeStep, Mute)):
        return await _run_volume(intent, desktop)
    raise ValueError(f"Unsupported intent: {intent!r}")


async def execute(
    intent: Intent,
    desktop: DesktopClient,
    mode: policy.Mode,
    *,
    clock: Callable[[], datetime] | None = None,
    gate: Callable[[str, Mapping[str, object], policy.Mode], policy.Decision] | None = None,
) -> FinalResponse:
    """Execute a fast-path intent, gated by policy and the desktop client."""
    if isinstance(intent, Stop):
        raise ValueError("Stop is handled by the orchestrator, not executed")
    tool, args = _tool_call(intent)
    decision = await _gated(gate or policy.gate, tool, args, mode)
    if not decision.allowed:
        return responses.blocked(decision, mode)
    try:
        return await _run(intent, desktop, clock or _local_now)
    except DesktopError as exc:
        if isinstance(intent, (OpenApp, CloseApp)) and exc.code in (
            "NOT_FOUND",
            "AMBIGUOUS",
        ):
            raise FastPathDeclined(f"{exc.code}: {exc.message}") from exc
        return responses.desktop_failure(_action(intent), exc)
