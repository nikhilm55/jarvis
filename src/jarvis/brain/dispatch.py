"""Per-turn tool handler: routes the model's tool calls and enforces the step limit."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from jarvis.brain.clock import TurnClock
from jarvis.brain.desktop_tools import DesktopLike, call_desktop  # gate-ok: via MCP impl
from jarvis.brain.failures import ToolError, step_limit_response
from jarvis.brain.respond import RespondGate
from jarvis.contract import FinalResponse, sanitise_spoken

_T = TypeVar("_T")

OnSay = Callable[[str], Awaitable[None]]
OnAsk = Callable[[str, list[str]], Awaitable[str]]

_STEP_GRACE = 3
_MAX_TEXT = 500
_MAX_OPTIONS = 10
_MAX_OPTION = 100


@dataclass(frozen=True)
class TurnHooks:
    """Hooks the turn invokes to speak, ask, and finish."""

    on_say: OnSay
    on_ask: OnAsk
    finish: Callable[[FinalResponse], None]
    clock: TurnClock


class TurnTools:
    """Per-turn tool handler that routes model tool calls and enforces limits."""

    def __init__(
        self, turn_id: str, hooks: TurnHooks, desktop: DesktopLike, max_steps: int
    ) -> None:
        """Create a turn handler bound to a turn id, hooks, desktop, and step budget."""
        self._hooks = hooks
        self._desktop = desktop
        self._max_steps = max_steps
        self._steps = 0
        self._closed = False
        self._inflight: set[asyncio.Task[Any]] = set()
        self._gate = RespondGate(turn_id, hooks.finish)

    @property
    def steps(self) -> int:
        """Tool calls counted so far."""
        return self._steps

    @property
    def repair_used(self) -> bool:
        """Whether the contract repair path has already been used this turn."""
        return self._gate.repair_used

    @property
    def final(self) -> FinalResponse | None:
        """The final response that resolved this turn, if any."""
        return self._gate.final

    def close(self) -> None:
        """Mark the turn over so further tool calls are rejected."""
        self._closed = True
        for task in self._inflight:
            task.cancel()

    async def _run(self, awaitable: Awaitable[_T]) -> _T:
        """Run an awaitable, tracking it as in-flight and handling cancellation."""
        task = asyncio.ensure_future(awaitable)
        self._inflight.add(task)
        try:
            return await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if task.cancelled() and current is not None and current.cancelling() == 0:
                raise ToolError("the turn ended while this was running") from None
            raise
        finally:
            self._inflight.discard(task)

    async def __call__(self, policy_name: str, args: dict[str, object]) -> object:
        """Route a single tool call for the current turn."""
        if self._closed:
            raise ToolError("no active turn: this turn has already ended")
        if policy_name == "jarvis.respond":
            return self._gate.submit(args)
        if self._gate.final is not None:
            raise ToolError("respond was already accepted; the turn is over")
        self._steps += 1
        if self._steps > self._max_steps + _STEP_GRACE:
            self._gate.force(step_limit_response(self._max_steps))
            raise ToolError("step limit exceeded: the turn has been ended")
        if self._steps > self._max_steps:
            raise ToolError("step limit reached: call respond now with what you have")
        if policy_name == "jarvis.say":
            return await self._say(args)
        if policy_name == "jarvis.ask":
            return await self._ask(args)
        if policy_name.startswith("desktop."):
            return await call_desktop(self._desktop, policy_name, args)  # gate-ok: via MCP impl
        raise ToolError(f"unknown tool {policy_name}")

    async def _say(self, args: dict[str, object]) -> str:
        """Speak a sanitised text to the user."""
        text = _text(args, "text")
        spoken = sanitise_spoken(text)
        if not spoken:
            raise ToolError("text has nothing speakable")
        await self._run(self._hooks.on_say(spoken))
        return "ok"

    async def _ask(self, args: dict[str, object]) -> str:
        """Ask the user a question, optionally with options, and return their answer."""
        question = sanitise_spoken(_text(args, "question"))
        if not question:
            raise ToolError("question has nothing speakable")
        options = _options(args.get("options"))
        self._hooks.clock.pause()
        try:
            return await self._run(self._hooks.on_ask(question, options))
        finally:
            self._hooks.clock.resume()


def _text(args: dict[str, object], key: str) -> str:
    """Fetch a required non-empty short string argument."""
    value = args.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a non-empty string of at most {_MAX_TEXT} characters")
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_TEXT:
        raise ToolError(f"{key} must be a non-empty string of at most {_MAX_TEXT} characters")
    return stripped


def _options(value: object) -> list[str]:
    """Normalise an optional options argument into a short list of short strings."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolError("options must be a short list of short strings")
    if len(value) > _MAX_OPTIONS:
        raise ToolError("options must be a short list of short strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolError("options must be a short list of short strings")
        stripped = item.strip()
        if not stripped or len(stripped) > _MAX_OPTION:
            raise ToolError("options must be a short list of short strings")
        cleaned = sanitise_spoken(stripped)
        if not cleaned:
            raise ToolError("options must be a short list of short strings")
        result.append(cleaned)
    return result
