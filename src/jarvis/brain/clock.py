"""A turn's wall-time budget that pauses while the user answers a question."""

import asyncio


class TurnClock:
    """A turn's wall-time budget; it stops running while the user answers a question."""

    def __init__(self) -> None:
        """Initialise with no scope, pause depth 0, and no remaining budget."""
        self._scope: asyncio.Timeout | None = None
        self._depth = 0
        self._remaining: float | None = None

    def attach(self, scope: asyncio.Timeout) -> None:
        """Store the timeout scope used to drive the turn budget."""
        self._scope = scope

    def pause(self) -> None:
        """Increment pause depth and freeze the budget on the first pause."""
        self._depth += 1
        if self._depth == 1 and self._scope is not None:
            when = self._scope.when()
            if when is not None:
                loop = asyncio.get_running_loop()
                self._remaining = max(0.0, when - loop.time())
                self._scope.reschedule(None)

    def resume(self) -> None:
        """Decrement pause depth and restore the budget on the last resume."""
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0 and self._scope is not None and self._remaining is not None:
            loop = asyncio.get_running_loop()
            self._scope.reschedule(loop.time() + self._remaining)
            self._remaining = None
