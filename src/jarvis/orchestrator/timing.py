"""Every duration the voice loop uses, in one place so tests can shrink them."""

from dataclasses import dataclass
from typing import Self

from jarvis.config import Settings

__all__ = ["Timing"]


@dataclass(frozen=True)
class Timing:
    """Windows and delays of the turn lifecycle (FRS 4.2, R47-R52)."""

    listen_window_s: float = 5.0
    reply_window_s: float = 8.0
    thinking_after_s: float = 1.2
    trailing_s: float = 0.7
    deaf_tail_s: float = 0.3
    min_silence_ms: int = 400
    inactivity_reset_s: float = 600.0

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build a Timing from the application Settings."""
        return cls(
            trailing_s=settings.audio.trailing_ms / 1000,
            inactivity_reset_s=float(settings.brain.inactivity_reset_s),
        )
