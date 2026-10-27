"""Answers that arrive from the HUD (buttons, keys, the typed box) for the open question."""

import asyncio
from dataclasses import dataclass
from typing import Literal

__all__ = ["HudAnswer", "HudAnswers", "HudMethod"]

HudMethod = Literal["button", "key", "typed"]


@dataclass(frozen=True)
class HudAnswer:
    """One answer from the HUD: "yes"/"no" for a button or key, free text when typed."""

    text: str
    method: HudMethod


class HudAnswers:
    """Hands a HUD answer to the question that is open, if any; one question at a time."""

    def __init__(self) -> None:
        """Start with no open question."""
        self._open: asyncio.Future[HudAnswer] | None = None

    def open(self) -> asyncio.Future[HudAnswer]:
        """Open a question; a previous one still open is closed unanswered."""
        self.close()
        self._open = asyncio.get_running_loop().create_future()
        return self._open

    def post(self, answer: HudAnswer) -> bool:
        """Deliver `answer` to the open question; False when nothing is waiting for one."""
        future = self._open
        if future is None or future.done():
            return False
        future.set_result(answer)
        return True

    def close(self, future: asyncio.Future[HudAnswer] | None = None) -> None:
        """Close the open question (only `future`'s, when given) so late answers are refused."""
        if future is not None and future is not self._open:
            return
        if self._open is not None and not self._open.done():
            self._open.cancel()
        self._open = None

    @property
    def waiting(self) -> bool:
        """True while a question is open and unanswered."""
        return self._open is not None and not self._open.done()
