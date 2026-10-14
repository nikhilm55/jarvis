"""Remembers the brain's tool calls of the running turn for the activity record (FR-LOG-01)."""

from jarvis.activity import ToolCallRecord
from jarvis.mcp import Dispatch

__all__ = ["ToolTrace"]

_MAX_CALLS = 200


class ToolTrace:
    """Records tool calls made during a turn for the activity log."""

    def __init__(self) -> None:
        """Initialise an empty call buffer."""
        self._calls: list[ToolCallRecord] = []

    def wrap(self, inner: Dispatch) -> Dispatch:
        """Return a dispatch that records each call before delegating to inner."""

        async def traced(name: str, args: dict[str, object]) -> object:
            """Record the call (if capacity remains) then await the inner dispatch."""
            if len(self._calls) < _MAX_CALLS:
                self._calls.append(ToolCallRecord(name, dict(args)))
            return await inner(name, args)

        return traced

    def take(self) -> list[ToolCallRecord]:
        """Return the recorded calls and reset the buffer to empty."""
        calls = self._calls
        self._calls = []
        return calls
