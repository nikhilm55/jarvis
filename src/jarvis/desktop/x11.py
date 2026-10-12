"""EWMH window helpers over python-xlib."""

import contextlib
import os
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass

from Xlib import X, display, error
from Xlib.protocol import event

from jarvis.desktop.apps import AppEntry


class X11Error(Exception):
    """Raised when an X11 operation fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class WindowInfo:
    """A snapshot of a top-level window."""

    window_id: int
    wm_instance: str
    wm_class: str
    pid: int | None
    title: str


@contextlib.contextmanager
def _session(disp: display.Display | None) -> Iterator[display.Display]:
    """Yield an open display, closing a caller-supplied one untouched."""
    if disp is None:
        d = open_display()
        try:
            yield d
        finally:
            d.close()
    else:
        yield disp


def open_display() -> display.Display:
    """Open the default X11 display or raise X11Error."""
    if not os.environ.get("DISPLAY"):
        raise X11Error("UNSUPPORTED_ON_PLATFORM", "no X11 display available")
    try:
        return display.Display()
    except (error.DisplayError, OSError) as exc:
        raise X11Error("UNSUPPORTED_ON_PLATFORM", "no X11 display available") from exc


def _read_window(disp: display.Display, wid: int) -> WindowInfo | None:
    """Build a WindowInfo for wid, returning None if the window is gone."""
    try:
        win = disp.create_resource_object("window", wid)
        wm_class = win.get_wm_class()
        instance = wm_class[0] if wm_class else ""
        klass = wm_class[1] if wm_class else ""

        pid_prop = win.get_full_property(disp.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
        pid: int | None = None
        if pid_prop is not None:
            pid = int(pid_prop.value[0])

        title_prop = win.get_full_property(disp.intern_atom("_NET_WM_NAME"), X.AnyPropertyType)
        title = ""
        if title_prop is not None:
            title = bytes(title_prop.value).decode("utf-8", errors="replace")

        return WindowInfo(
            window_id=int(wid),
            wm_instance=str(instance),
            wm_class=str(klass),
            pid=pid,
            title=title,
        )
    except error.XError:
        return None


def list_windows(disp: display.Display | None = None) -> list[WindowInfo]:
    """Return the current top-level windows in _NET_CLIENT_LIST order."""
    with _session(disp) as d:
        root = d.screen().root
        atom = d.intern_atom("_NET_CLIENT_LIST")
        prop = root.get_full_property(atom, X.AnyPropertyType)
        if prop is None:
            return []
        ids = [int(x) for x in prop.value]
        result: list[WindowInfo] = []
        for wid in ids:
            info = _read_window(d, wid)
            if info is not None:
                result.append(info)
        return result


def close_window(window_id: int, disp: display.Display | None = None) -> None:
    """Send an EWMH _NET_CLOSE_WINDOW message to the given window."""
    with _session(disp) as d:
        root = d.screen().root
        try:
            win = d.create_resource_object("window", window_id)
            ev = event.ClientMessage(
                window=win,
                client_type=d.intern_atom("_NET_CLOSE_WINDOW"),
                data=(32, [X.CurrentTime, 1, 0, 0, 0]),
            )
            root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            d.sync()  # not flush(): we disconnect next, the server must have the request first
        except error.XError as exc:
            raise X11Error("NOT_FOUND", "window is gone") from exc


def app_matches(app: AppEntry, window: WindowInfo) -> bool:
    """Return True if the window belongs to the given app entry."""
    if app.startup_wm_class:
        target = app.startup_wm_class.lower()
        return window.wm_class.lower() == target or window.wm_instance.lower() == target
    wanted = {app.desktop_id.removesuffix(".desktop").casefold(), app.exec_name.casefold()}
    seen = {window.wm_class.casefold(), window.wm_instance.casefold()}
    return bool((wanted - {""}) & (seen - {""}))


def new_windows(before: Collection[int], now: Iterable[WindowInfo]) -> list[WindowInfo]:
    """Return the windows in `now` whose id is not in `before`."""
    before_set = set(before)
    return [w for w in now if w.window_id not in before_set]
