"""'Jarvis is controlling your PC', with a Stop button, while input tools run (FR-SAFE-06)."""

import contextlib
from collections.abc import AsyncIterator

from jarvis.orchestrator.hud import HudEvent, HudSink

__all__ = ["CONTROLLING", "ControlIndicator"]

CONTROLLING = "Jarvis is controlling your PC"


class ControlIndicator:
    """Shows the indicator while at least one input tool runs; nested runs show it once."""

    def __init__(self, hud: HudSink) -> None:
        """Bind the HUD sink the indicator is shown on."""
        self._hud = hud
        self._depth = 0

    @contextlib.asynccontextmanager
    async def driving(self) -> AsyncIterator[None]:
        """Show the indicator for the duration of the block, and take it down after."""
        self._depth += 1
        if self._depth == 1:
            await self._hud(HudEvent("controlling", CONTROLLING, {"stop": True}))
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                await self._hud(HudEvent("controlling", "", {"closed": True}))
