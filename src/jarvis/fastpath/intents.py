"""Intent types the fast path can recognise (FRS 5.4)."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OpenApp:
    """Intent to open a named application."""

    name: str


@dataclass(frozen=True)
class CloseApp:
    """Intent to close a named application."""

    name: str


@dataclass(frozen=True)
class FocusWindow:
    """Intent to bring a named app's window to the front."""

    name: str


@dataclass(frozen=True)
class WindowAction:
    """Intent to minimise, maximise or close a named app's window."""

    name: str
    op: Literal["minimize", "maximize", "close"]


@dataclass(frozen=True)
class TellTime:
    """Intent to announce the current time."""


@dataclass(frozen=True)
class TellDate:
    """Intent to announce the current date."""


@dataclass(frozen=True)
class VolumeSet:
    """Intent to set the volume to a specific percentage."""

    percent: int

    def __post_init__(self) -> None:
        if isinstance(self.percent, bool) or not isinstance(self.percent, int):
            raise ValueError("percent must be 0-100")
        if not 0 <= self.percent <= 100:
            raise ValueError("percent must be 0-100")


@dataclass(frozen=True)
class VolumeStep:
    """Intent to adjust the volume by a fixed step."""

    delta: int

    def __post_init__(self) -> None:
        if isinstance(self.delta, bool) or not isinstance(self.delta, int):
            raise ValueError("delta must be +10 or -10")
        if self.delta not in (10, -10):
            raise ValueError("delta must be +10 or -10")


@dataclass(frozen=True)
class Mute:
    """Intent to toggle or set the mute state."""

    on: bool


@dataclass(frozen=True)
class Stop:
    """Intent to stop the current action."""


Intent = (
    OpenApp
    | CloseApp
    | FocusWindow
    | WindowAction
    | TellTime
    | TellDate
    | VolumeSet
    | VolumeStep
    | Mute
    | Stop
)

__all__ = [
    "CloseApp",
    "FocusWindow",
    "Intent",
    "Mute",
    "OpenApp",
    "Stop",
    "TellDate",
    "TellTime",
    "VolumeSet",
    "VolumeStep",
    "WindowAction",
]
