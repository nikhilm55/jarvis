"""HUD events the orchestrator emits for the UI to render (FRS 4.2, Task 12 consumes them)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from jarvis.log import get_logger

HudState = Literal[
    "idle",
    "listening",
    "transcript",
    "thinking",
    "acting",
    "speaking",
    "error",
    "reply",
]


@dataclass(frozen=True)
class HudEvent:
    """One state change for the HUD; `text` is what to show, `extra` optional structured data."""

    state: HudState
    text: str = ""
    extra: dict[str, object] = field(default_factory=dict)


HudSink = Callable[[HudEvent], Awaitable[None]]


async def null_sink(event: HudEvent) -> None:
    """Discard the event (the default sink)."""
    return None


def safe_sink(sink: HudSink) -> HudSink:
    """Wrap a sink so failures are logged but never propagate."""
    logger = get_logger("hud")

    async def guarded(event: HudEvent) -> None:
        try:
            await sink(event)
        except Exception:
            # A broken HUD must never stop start-up or a timer.
            logger.warning("HUD sink failed", exc_info=True)

    return guarded


__all__ = ["HudEvent", "HudSink", "HudState", "null_sink", "safe_sink"]
