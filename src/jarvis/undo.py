"""Undo (FR-SAFE-05, R90): "Jarvis, undo that" reverses the last undoable action.

Tools that can be reversed push an entry with what to say and how to revert it. Only the most
recent entries are kept, and only for an hour: an undo much later is more likely a surprise
than a wish.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

__all__ = ["NOTHING_TO_UNDO", "UndoEntry", "UndoLog"]

NOTHING_TO_UNDO = "There's nothing for me to undo."
_KEEP = 10
_FRESH_S = 3600.0


@dataclass(frozen=True)
class UndoEntry:
    """An action that can be reversed: `revert` does it and returns what to say."""

    what: str  # e.g. "moved 412 files from Downloads to the trash"
    revert: Callable[[], Awaitable[str]]
    at: float = 0.0


class UndoLog:
    """The last few undoable actions, newest last."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """`clock` is a test seam."""
        self._clock = clock
        self._entries: list[UndoEntry] = []

    def push(self, what: str, revert: Callable[[], Awaitable[str]]) -> None:
        """Remember an undoable action."""
        self._entries = [*self._entries[-(_KEEP - 1) :], UndoEntry(what, revert, self._clock())]

    def last(self) -> UndoEntry | None:
        """The newest action still worth undoing, or None."""
        while self._entries and self._clock() - self._entries[-1].at > _FRESH_S:
            self._entries.pop()
        return self._entries[-1] if self._entries else None

    async def undo_last(self) -> str:
        """Revert the newest action and say what happened."""
        entry = self.last()
        if entry is None:
            return NOTHING_TO_UNDO
        self._entries.pop()
        return await entry.revert()
