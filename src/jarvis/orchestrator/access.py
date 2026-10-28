"""The access badge (FR-CON-14): "Reading Teams…" while a tool touches a personal source."""

import contextlib
from collections.abc import AsyncIterator

from jarvis.consent.wording import source_name
from jarvis.orchestrator.hud import HudEvent, HudSink

__all__ = ["AccessBadge", "badge_text"]


def badge_text(scopes: tuple[str, ...]) -> str:
    """ "Reading Teams…", "Using Teams…" for a write, "Reading Teams and Calendar…"."""
    sources: dict[str, set[str]] = {}
    for scope in scopes:
        source, _, access = scope.partition(":")
        sources.setdefault(source, set()).add(access)
    names = [source_name(s) for s in sorted(sources)]
    verb = "Using" if any("write" in a for a in sources.values()) else "Reading"
    return f"{verb} {' and '.join(names)}…"


class AccessBadge:
    """Shows the badge while a tool touching personal data runs; nested runs keep it up."""

    def __init__(self, hud: HudSink) -> None:
        """Bind the HUD sink the badge is shown on."""
        self._hud = hud
        self._depth = 0

    @contextlib.asynccontextmanager
    async def touching(self, scopes: tuple[str, ...]) -> AsyncIterator[None]:
        """Show the badge for `scopes` during the block, and take it down after."""
        self._depth += 1
        sources = sorted({scope.partition(":")[0] for scope in scopes})
        await self._hud(HudEvent("access_badge", badge_text(scopes), {"sources": sources}))
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                await self._hud(HudEvent("access_badge", "", {"closed": True}))
