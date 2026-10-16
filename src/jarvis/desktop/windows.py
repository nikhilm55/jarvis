"""Window management over EWMH, through an injected X port (FR-PC-02).

`WindowManager` holds the logic (find a window, focus it, minimise it, ...) and checks every
result on the window itself. It talks to X only through `XPort`, so the tests drive it with a
fake window manager and `xport.py` is the one place that touches python-xlib.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.desktop.x11 import X11Error

__all__ = [
    "Rect",
    "WindowError",
    "WindowManager",
    "WindowView",
    "XPort",
    "make_ref",
    "parse_ref",
]

_REF = re.compile(r"x11:0x([0-9a-f]{1,8})")
_HIDDEN_TYPES = frozenset({"DOCK", "DESKTOP", "SPLASH", "NOTIFICATION", "TOOLTIP", "MENU"})


def make_ref(wid: int) -> str:
    """The stable reference to a window: `x11:` plus its id in hex."""
    return f"x11:{wid:#x}"


def parse_ref(text: str) -> int | None:
    """The window id in a reference made by `make_ref`, or None if `text` is not one."""
    match = _REF.fullmatch(text.strip().lower())
    return int(match.group(1), 16) if match else None


class WindowError(X11Error):
    """A window operation failed; `alternatives` are the closest window titles, if any."""

    def __init__(self, code: str, message: str, alternatives: Sequence[str] = ()) -> None:
        super().__init__(code, message)
        self.alternatives = tuple(alternatives)


@dataclass(frozen=True)
class Rect:
    """A rectangle in root-window coordinates."""

    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def intersect(self, other: "Rect") -> "Rect":
        """The overlap of two rectangles (zero-sized if they do not meet)."""
        left, top = max(self.x, other.x), max(self.y, other.y)
        right = min(self.x + self.w, other.x + other.w)
        bottom = min(self.y + self.h, other.y + other.h)
        return Rect(left, top, max(0, right - left), max(0, bottom - top))


class XPort(Protocol):
    """What the window logic needs from X: live reads that never raise for a gone window."""

    def stacking(self) -> list[int]:
        """Managed window ids, bottom to top (`_NET_CLIENT_LIST_STACKING`)."""
        ...

    def active_window(self) -> int | None:
        """The focused window (`_NET_ACTIVE_WINDOW`), or None."""
        ...

    def title(self, wid: int) -> str: ...

    def wm_class(self, wid: int) -> tuple[str, str]:
        """(instance, class) of WM_CLASS; empty strings if unset."""
        ...

    def window_types(self, wid: int) -> frozenset[str]:
        """`_NET_WM_WINDOW_TYPE` names without the prefix: NORMAL, DIALOG, DOCK, ..."""
        ...

    def states(self, wid: int) -> frozenset[str]:
        """`_NET_WM_STATE` names without the prefix: HIDDEN, MAXIMIZED_VERT, FULLSCREEN, ..."""
        ...

    def rect(self, wid: int) -> Rect | None:
        """The client area in root coordinates, or None if the window is gone."""
        ...

    def frame_extents(self, wid: int) -> tuple[int, int, int, int]:
        """Decoration widths (left, right, top, bottom); zeros if the window has none."""
        ...

    def monitors(self) -> list[Rect]:
        """The monitors, ordered left to right then top to bottom."""
        ...

    def workarea(self) -> Rect:
        """The usable area of the current desktop, panels excluded (`_NET_WORKAREA`)."""
        ...

    def server_time(self) -> int:
        """The X server's current timestamp."""
        ...

    def send(self, wid: int, message: str, data: Sequence[int | str]) -> None:
        """Send a 32-bit client message about window `wid` to the root window.

        A `str` in `data` is an atom name, interned by the implementation.
        """
        ...


@dataclass(frozen=True)
class WindowView:
    """One window as the tools report it."""

    wid: int
    title: str
    wm_instance: str
    wm_class: str
    monitor: int
    state: tuple[str, ...]  # any of minimized, maximized, focused; ("normal",) if none

    @property
    def ref(self) -> str:
        return make_ref(self.wid)


class WindowManager:
    """List, find, focus and rearrange windows through an `XPort`."""

    def __init__(
        self,
        port: XPort,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._port = port
        self._sleep = sleep
        self._now = now

    def _view(self, wid: int, active: int | None, monitors: Sequence[Rect]) -> WindowView:
        states = self._port.states(wid)
        state = [
            name
            for name, on in (
                ("minimized", "HIDDEN" in states),
                ("maximized", {"MAXIMIZED_VERT", "MAXIMIZED_HORZ"} <= states),
                ("focused", wid == active),
            )
            if on
        ]
        rect = self._port.rect(wid)
        centre = rect.center if rect is not None else None
        monitor = next(
            (i for i, m in enumerate(monitors) if centre is not None and m.contains(*centre)), 0
        )
        instance, klass = self._port.wm_class(wid)
        return WindowView(
            wid, self._port.title(wid), instance, klass, monitor, tuple(state) or ("normal",)
        )

    def view(self, wid: int) -> WindowView:
        """The window's state right now."""
        return self._view(wid, self._port.active_window(), self._port.monitors())

    def list(self) -> list[WindowView]:
        """The user's windows, frontmost first.

        Windows of type DOCK, DESKTOP, SPLASH, NOTIFICATION, TOOLTIP or MENU are left out.
        The monitor is the index in `port.monitors()` of the one holding the window's centre
        (0 if none does). The state is "minimized" if HIDDEN is set, "maximized" if both
        MAXIMIZED_VERT and MAXIMIZED_HORZ are, and "focused" if it is the active window.
        """
        active, monitors = self._port.active_window(), self._port.monitors()
        return [
            self._view(wid, active, monitors)
            for wid in reversed(self._port.stacking())
            if not self._port.window_types(wid) & _HIDDEN_TYPES
        ]
