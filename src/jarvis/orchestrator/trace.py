"""Remembers the brain's tool calls of the running turn for the activity record (FR-LOG-01)."""

from jarvis.activity import ToolCallRecord
from jarvis.config import PolicySettings
from jarvis.mcp import Dispatch
from jarvis.policy.decision import TurnContext
from jarvis.policy.model import Mode

__all__ = ["ToolTrace"]

_MAX_CALLS = 200


class ToolTrace:
    """Records tool calls made during a turn for the activity log."""

    def __init__(self, policy: PolicySettings | None = None, mode: Mode = "safe") -> None:
        """Start empty; `policy` and `mode` are what a call is judged by outside any turn."""
        self._policy = policy or PolicySettings()
        self._mode = mode
        self._calls: list[ToolCallRecord] = []
        self.ctx: TurnContext | None = None  # the running turn's policy context

    def wrap(self, inner: Dispatch) -> Dispatch:
        """Return a dispatch that records each call before delegating to inner."""

        async def traced(name: str, args: dict[str, object]) -> object:
            """Record the call (if capacity remains) then await the inner dispatch."""
            if len(self._calls) < _MAX_CALLS:
                self._calls.append(ToolCallRecord(name, dict(args)))
            return await inner(name, args)

        return traced

    def turn_context(self) -> TurnContext:
        """The running turn's context; between turns an anonymous one with the user's lists."""
        return self.ctx or TurnContext("no-turn", self._policy, self._mode)

    def take(self) -> list[ToolCallRecord]:
        """Return the recorded calls and reset the buffer and the turn context."""
        calls = self._calls
        self._calls = []
        self.ctx = None
        return calls
