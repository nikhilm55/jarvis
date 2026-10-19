"""Window management over EWMH, through an injected X port (FR-PC-02).

`WindowManager` holds the logic (find a window, focus it, minimise it, ...) and checks every
result on the window itself. It talks to X only through `XPort`, so the tests drive it with a
fake window manager and `xport.py` is the one place that touches python-xlib.
"""

import difflib
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.desktop.x11 import X11Error

__all__ = [
    "WINDOW_OPS",
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
_SETTLE_S = 1.0  # how long a window manager gets to show the effect of a request
_POLL_S = 0.05
_SOURCE_PAGER = 2  # EWMH source indication: a pager or similar tool, which may take focus
_NEAR_TITLES = 5
_STATE_REMOVE, _STATE_ADD = 0, 1
_MAX_FLAGS = frozenset({"MAXIMIZED_VERT", "MAXIMIZED_HORZ"})
_MAXIMIZED = ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")
WINDOW_OPS = (
    "minimize",
    "maximize",
    "restore",
    "close",
    "snap_left",
    "snap_right",
    "move_to_monitor",
    "tile",
)


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


_NO_MATCH = 3


def _rank(wanted: str, view: WindowView) -> int:
    """0 if `wanted` is the whole title or class, 1 if it starts one, 2 if it is inside one."""
    names = [n for n in (view.title, view.wm_instance, view.wm_class) if n]
    folded = [n.casefold() for n in names]
    if wanted in folded:
        return 0
    if any(n.startswith(wanted) for n in folded):
        return 1
    if any(wanted in n for n in folded):
        return 2
    return _NO_MATCH


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

    def _wait_for(self, done: Callable[[], bool]) -> bool:
        """Poll `done` every 50 ms for up to a second; True as soon as it holds."""
        deadline = self._now() + _SETTLE_S
        while not done():
            if self._now() >= deadline:
                return False
            self._sleep(_POLL_S)
        return True

    def _view(self, wid: int, active: int | None, monitors: Sequence[Rect]) -> WindowView:
        states = self._port.states(wid)
        state = [
            name
            for name, on in (
                ("minimized", "HIDDEN" in states),
                ("maximized", states >= _MAX_FLAGS),
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

    def resolve(self, target: str) -> int:
        """The id of the window `target` names: a ref from `list`, or words of a title or app.

        A ref must belong to a listed window. Words match, case-insensitively, the window's
        title or WM_CLASS: an exact match beats a prefix, which beats a substring. If the best
        matches are all windows of one app, the frontmost wins; if they are of different apps
        raise WindowError("AMBIGUOUS", ...). No match raises WindowError("NOT_FOUND", ...)
        whose `alternatives` are up to five of the closest titles (difflib).
        """
        views = self.list()
        wid = parse_ref(target)
        if wid is not None and any(v.wid == wid for v in views):
            return wid
        wanted = target.strip().casefold()
        if not wanted:
            raise WindowError("INVALID_ARGUMENT", "name the window: a ref or words of its title")
        ranked = [(_rank(wanted, v), v) for v in views]
        best = min((rank for rank, _ in ranked), default=_NO_MATCH)
        matches = [v for rank, v in ranked if rank == best and rank < _NO_MATCH]
        if not matches:
            near = difflib.get_close_matches(
                target.strip(), [v.title for v in views], n=_NEAR_TITLES, cutoff=0.3
            )
            raise WindowError("NOT_FOUND", f"no window matches {target!r}", near)
        if len({v.wm_class for v in matches}) > 1:
            names = ", ".join(sorted({v.title for v in matches}))
            raise WindowError("AMBIGUOUS", f"{target!r} matches several apps: {names}")
        return matches[0].wid  # one app: the frontmost of its windows (the list is in order)

    def _activate(self, wid: int) -> None:
        """Ask the window manager to focus the window, as a pager would (source 2)."""
        active = self._port.active_window() or 0
        data = [_SOURCE_PAGER, self._port.server_time(), active, 0, 0]
        self._port.send(wid, "_NET_ACTIVE_WINDOW", data)

    def focus(self, target: str) -> WindowView:
        """Bring the window to the front and focus it, and check that it is focused.

        A minimised window is restored first. Sends `_NET_ACTIVE_WINDOW` (source 2, the
        server time, the current active window), then polls up to 1 s for the active window
        to be the target; otherwise WindowError("ACTION_FAILED", ...) naming what to try.
        """
        wid = self.resolve(target)
        if "HIDDEN" in self._port.states(wid):  # EWMH restores a window by activating it
            self._activate(wid)
            if not self._wait_for(lambda: "HIDDEN" not in self._port.states(wid)):
                raise WindowError(
                    "ACTION_FAILED",
                    "the window is still minimised after asking to restore it. "
                    "Click its icon in the dock, then ask again.",
                )
        self._activate(wid)
        if not self._wait_for(lambda: self._port.active_window() == wid):
            raise WindowError(
                "ACTION_FAILED",
                "the window did not take focus; the desktop may be blocking focus changes. "
                "Click the window yourself, then ask again.",
            )
        return self.view(wid)

    def window_op(
        self,
        target: str,
        op: str,
        *,
        monitor: int | None = None,
        with_targets: Sequence[str] = (),
    ) -> Sequence[WindowView]:
        """Run `op` on the window `target` names and check the result on the window itself.

        Returns the windows after the op (for close, as they were before it). An unknown op is
        INVALID_ARGUMENT; an op the window manager did not carry out is ACTION_FAILED.
        """
        if op not in WINDOW_OPS:
            raise WindowError(
                "INVALID_ARGUMENT", f"unknown window op {op!r}; use one of {', '.join(WINDOW_OPS)}"
            )
        wid = self.resolve(target)
        if op == "close":
            return [self._close(wid)]
        handler = {
            "minimize": self._minimize,
            "maximize": self._maximize,
            "restore": self._restore,
        }[op]
        handler(wid)
        return [self.view(wid)]

    def _failed(self, op: str, what: str, remedy: str) -> WindowError:
        return WindowError("ACTION_FAILED", f"{op} did not work: {what}. {remedy}")

    def _states(self, wid: int) -> frozenset[str]:
        return self._port.states(wid)

    def _unhide(self, wid: int, op: str) -> None:
        """Restore a minimised window; EWMH does it by activating the window."""
        if "HIDDEN" not in self._states(wid):
            return
        self._activate(wid)
        if not self._wait_for(lambda: "HIDDEN" not in self._states(wid)):
            raise self._failed(op, "the window stayed minimised", "Click its icon in the dock.")

    def _set_maximized(self, wid: int, on: bool) -> None:
        action = _STATE_ADD if on else _STATE_REMOVE
        self._port.send(wid, "_NET_WM_STATE", [action, *_MAXIMIZED, _SOURCE_PAGER, 0])

    def _minimize(self, wid: int) -> None:
        if "HIDDEN" in self._states(wid):
            return
        self._port.send(wid, "WM_CHANGE_STATE", [3])  # IconicState
        if not self._wait_for(lambda: "HIDDEN" in self._states(wid)):
            raise self._failed("minimize", "the window stayed visible", "Minimise it yourself.")

    def _maximize(self, wid: int) -> None:
        self._unhide(wid, "maximize")
        if self._states(wid) >= _MAX_FLAGS:
            return
        self._set_maximized(wid, True)
        if not self._wait_for(lambda: self._states(wid) >= _MAX_FLAGS):
            raise self._failed("maximize", "the window did not fill the screen", "Try again.")

    def _restore(self, wid: int) -> None:
        self._unhide(wid, "restore")
        if not _MAX_FLAGS & self._states(wid):
            return
        self._set_maximized(wid, False)
        if not self._wait_for(lambda: not _MAX_FLAGS & self._states(wid)):
            raise self._failed("restore", "the window stayed maximised", "Try again.")

    def _close(self, wid: int) -> WindowView:
        before = self.view(wid)
        self._port.send(
            wid, "_NET_CLOSE_WINDOW", [self._port.server_time(), _SOURCE_PAGER, 0, 0, 0]
        )
        if not self._wait_for(lambda: wid not in self._port.stacking()):
            raise self._failed(
                "close", "the window is still open", "It may be asking to save first; check it."
            )
        return before
