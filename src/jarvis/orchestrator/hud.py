"""HUD events the orchestrator emits for the UI to render (FRS 4.2, Task 12 consumes them)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

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


__all__ = ["HudEvent", "HudSink", "HudState", "null_sink"]
