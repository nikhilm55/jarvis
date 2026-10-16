"""Test doubles for the fast-path executor: a fake desktop client, gates and a fixed clock."""

import asyncio
from collections.abc import Callable
from datetime import datetime

from jarvis.contract import ErrorInfo, FinalResponse
from jarvis.desktop.client import DesktopClient, DesktopError
from jarvis.fastpath import execute
from jarvis.fastpath.intents import Intent
from jarvis.policy import Mode
from jarvis.policy.decision import TurnContext

_RESULTS: dict[str, dict[str, object]] = {
    "open_app": {"app": "Calculator", "window_ids_new": [1]},
    "close_app": {"app": "Calculator", "closed": 1},
    "volume_set": {"percent": 40, "muted": False},
    "volume_step": {"percent": 50, "muted": False},
    "mute": {"percent": 40, "muted": True},
}


class FakeDesktop(DesktopClient):
    """Records every call in `events`; raises `error` or returns the canned result."""

    def __init__(
        self,
        events: list[str],
        results: dict[str, dict[str, object]] | None = None,
        error: DesktopError | None = None,
    ) -> None:
        super().__init__(["unused"])
        self.events = events
        self.error = error
        self.results = results or _RESULTS

    async def open_app(self, query: str) -> dict[str, object]:
        return self._record("open_app")

    async def close_app(self, query: str) -> dict[str, object]:
        return self._record("close_app")

    async def volume_set(self, pct: int) -> dict[str, object]:
        return self._record("volume_set")

    async def volume_step(self, delta: int) -> dict[str, object]:
        return self._record("volume_step")

    async def mute(self, on: bool) -> dict[str, object]:
        return self._record("mute")

    def _record(self, method: str) -> dict[str, object]:
        self.events.append(f"desktop.{method}")
        if self.error is not None:
            raise self.error
        return self.results[method]


def at(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> Callable[[], datetime]:
    return lambda: datetime(year, month, day, hour, minute)


def run(
    intent: Intent,
    desktop: FakeDesktop,
    mode: Mode,
    clock: Callable[[], datetime] | None = None,
    ctx: TurnContext | None = None,
) -> FinalResponse:
    return asyncio.run(execute(intent, desktop, mode, clock=clock, ctx=ctx))


def error_of(response: FinalResponse) -> ErrorInfo:
    assert response.error is not None
    return response.error
