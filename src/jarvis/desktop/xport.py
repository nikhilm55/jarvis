"""The python-xlib implementation of `XPort`: the only place the window logic touches X."""

import contextlib
import os
import time
from collections.abc import Callable, Iterator, Sequence

from Xlib import X, display, error
from Xlib.ext import randr
from Xlib.protocol import event

from jarvis.desktop.windows import Rect
from jarvis.desktop.x11 import X11Error, open_display

__all__ = ["WAYLAND_REMEDY", "XlibPort", "open_port", "pack_data"]

_MASK = X.SubstructureRedirectMask | X.SubstructureNotifyMask
_TIME_PROP = "_JARVIS_TIME"
_TIME_WAIT_S = 0.5


def pack_data(values: Sequence[int | str], intern: Callable[[str], int]) -> list[int]:
    """Five unsigned 32-bit words for a client message: names interned, negatives wrapped."""
    words = [(intern(v) if isinstance(v, str) else v) & 0xFFFFFFFF for v in values]
    return (words + [0] * 5)[:5]


class XlibPort:
    """`XPort` over one open display. Reads of a gone window give empty answers."""

    def __init__(self, disp: display.Display) -> None:
        self._d = disp
        self._root = disp.screen().root

    def _atom(self, name: str) -> int:
        return int(self._d.intern_atom(name))

    def _names(self, atoms: Sequence[int], prefix: str) -> frozenset[str]:
        names = set()
        for atom in atoms:
            with contextlib.suppress(error.XError):
                names.add(self._d.get_atom_name(int(atom)).removeprefix(prefix))
        return frozenset(names)

    def _cardinals(self, wid: int | None, name: str) -> list[int]:
        win = self._root if wid is None else self._d.create_resource_object("window", wid)
        try:
            prop = win.get_full_property(self._atom(name), X.AnyPropertyType)
        except error.XError:
            return []
        return [] if prop is None else [int(v) for v in prop.value]

    def stacking(self) -> list[int]:
        return self._cardinals(None, "_NET_CLIENT_LIST_STACKING") or self._cardinals(
            None, "_NET_CLIENT_LIST"
        )

    def active_window(self) -> int | None:
        values = self._cardinals(None, "_NET_ACTIVE_WINDOW")
        return values[0] if values and values[0] else None

    def title(self, wid: int) -> str:
        win = self._d.create_resource_object("window", wid)
        try:
            prop = win.get_full_property(self._atom("_NET_WM_NAME"), X.AnyPropertyType)
            if prop is not None:
                return bytes(prop.value).decode("utf-8", errors="replace")
            name = win.get_wm_name()
        except error.XError:
            return ""
        return name if isinstance(name, str) else ""

    def wm_class(self, wid: int) -> tuple[str, str]:
        try:
            found = self._d.create_resource_object("window", wid).get_wm_class()
        except error.XError:
            return ("", "")
        return (str(found[0]), str(found[1])) if found else ("", "")

    def window_types(self, wid: int) -> frozenset[str]:
        return self._names(self._cardinals(wid, "_NET_WM_WINDOW_TYPE"), "_NET_WM_WINDOW_TYPE_")

    def states(self, wid: int) -> frozenset[str]:
        return self._names(self._cardinals(wid, "_NET_WM_STATE"), "_NET_WM_STATE_")

    def rect(self, wid: int) -> Rect | None:
        win = self._d.create_resource_object("window", wid)
        try:
            geo = win.get_geometry()
            origin = self._root.translate_coords(win, 0, 0)
        except error.XError:
            return None
        return Rect(int(origin.x), int(origin.y), int(geo.width), int(geo.height))

    def frame_extents(self, wid: int) -> tuple[int, int, int, int]:
        values = self._cardinals(wid, "_NET_FRAME_EXTENTS")
        if len(values) != 4:
            return (0, 0, 0, 0)
        return (values[0], values[1], values[2], values[3])

    def monitors(self) -> list[Rect]:
        found: list[Rect] = []
        if self._d.has_extension("RANDR"):
            with contextlib.suppress(error.XError):
                found = [
                    Rect(m.x, m.y, m.width_in_pixels, m.height_in_pixels)
                    for m in randr.get_monitors(self._root).monitors
                ]
        if not found:
            geo = self._root.get_geometry()
            found = [Rect(0, 0, int(geo.width), int(geo.height))]
        return sorted(found, key=lambda r: (r.x, r.y))

    def workarea(self) -> Rect:
        areas = self._cardinals(None, "_NET_WORKAREA")
        current = self._cardinals(None, "_NET_CURRENT_DESKTOP")
        index = current[0] if current else 0
        if len(areas) >= 4 * (index + 1):
            x, y, w, h = areas[4 * index : 4 * index + 4]
            return Rect(x, y, w, h)
        return self.monitors()[0]

    def server_time(self) -> int:
        """The server's clock, read off a PropertyNotify that a throwaway window triggers.

        Falls back to CurrentTime (0) if no answer comes within half a second.
        """
        win = self._root.create_window(0, 0, 1, 1, 0, self._d.screen().root_depth)
        try:
            win.change_attributes(event_mask=X.PropertyChangeMask)
            win.change_property(self._atom(_TIME_PROP), self._atom("STRING"), 8, b"")
            self._d.flush()
            deadline = time.monotonic() + _TIME_WAIT_S
            while time.monotonic() < deadline:
                if not self._d.pending_events():
                    time.sleep(0.005)
                    continue
                ev = self._d.next_event()
                if ev.type == X.PropertyNotify and ev.window.id == win.id:
                    return int(ev.time)
        except error.XError:
            return int(X.CurrentTime)
        finally:
            with contextlib.suppress(error.XError):
                win.destroy()
                self._d.flush()
        return int(X.CurrentTime)

    def send(self, wid: int, message: str, data: Sequence[int | str]) -> None:
        try:
            win = self._d.create_resource_object("window", wid)
            ev = event.ClientMessage(
                window=win,
                client_type=self._atom(message),
                data=(32, pack_data(data, self._d.intern_atom)),
            )
            catch = error.CatchError(error.BadWindow)
            self._root.send_event(ev, event_mask=_MASK, onerror=catch)
            self._d.sync()
        except error.XError:
            return  # the window is gone: the caller's postcondition check reports it


WAYLAND_REMEDY = (
    "Jarvis controls windows through X11, and this is a Wayland session. Log out, choose "
    "'Ubuntu on Xorg' from the gear menu on the login screen, and sign in again."
)


@contextlib.contextmanager
def open_port() -> Iterator[XlibPort]:
    """An `XlibPort` on a fresh connection, closed afterwards.

    Raises X11Error("UNSUPPORTED_ON_PLATFORM", ...) with the remedy (ADR-0009, FR-PC-21) on a
    Wayland session, where XWayland would show only part of the windows, or with no display.
    """
    if os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland":
        raise X11Error("UNSUPPORTED_ON_PLATFORM", WAYLAND_REMEDY)
    disp = open_display()
    try:
        yield XlibPort(disp)
    finally:
        disp.close()
