"""Standalone HUD window process.

Runs as a separate process under the system python 3.12 with stdlib and gi
(PyGObject) only; it never imports the jarvis package or third-party code.
Exit codes: 0 normal, 2 no token, 78 no GUI. The window exits when its
parent process dies or on SIGTERM/SIGINT. The token arrives in the
environment (never argv) and reaches the page only in the URL fragment.
The window is click-through via an empty X input shape (X11 only), except
while a confirmation card shows (R82): then it takes clicks over the card's
rectangle only and takes keyboard focus, so the buttons, the keys and the
typed box work. The page says when, through the "hud" script message.
"""

import argparse
import ctypes
import ctypes.util
import json
import os
import signal
import sys
import urllib.parse
from typing import Any

EXIT_NO_GUI = 78
EXIT_USAGE = 2
TOKEN_ENV = "JARVIS_HUD_TOKEN"  # noqa: S105 - the variable name, not a secret
WINDOW_WIDTH = 612
WINDOW_HEIGHT = 420  # room for a confirmation card above the pill; the rest is click-through


class GuiUnavailable(Exception):
    """Raised when GTK 3 / WebKit2 4.1 cannot be loaded."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments requiring a --url option."""
    parser = argparse.ArgumentParser(prog="window.py")
    parser.add_argument("--url", required=True)
    return parser.parse_args(argv)


def placement(area: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int]:
    """Compute the top-centred, bottom-aligned window position for an area."""
    ax, ay, aw, ah = area
    return ax + (aw - width) // 2, ay + ah - height


def page_url(url: str, token: str) -> str:
    """Append the token to the url as a quoted URL fragment."""
    return f"{url}#{urllib.parse.quote(token, safe='')}"


def _load_x_libraries() -> tuple[Any, Any] | None:
    """Load libX11 and libXext, configuring ctypes signatures; None on failure."""
    x11_name = ctypes.util.find_library("X11")
    xext_name = ctypes.util.find_library("Xext")
    if x11_name is None or xext_name is None:
        return None
    x11 = ctypes.CDLL(x11_name)
    xext = ctypes.CDLL(xext_name)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XFlush.argtypes = x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xext.XShapeCombineRectangles.argtypes = [  # display, window, kind, x, y, rects, n, op, order
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    return x11, xext


class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


Rect = tuple[int, int, int, int]


def set_input_shape(xid: int, rect: Rect | None = None, x11: Any = None, xext: Any = None) -> bool:
    """Let clicks reach window `xid` only inside `rect` (None: nowhere); True on success."""
    if x11 is None or xext is None:
        loaded = _load_x_libraries()
        if loaded is None:
            return False
        x11, xext = loaded
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    rects = (_XRectangle * 1)(_XRectangle(*rect)) if rect is not None else None
    try:
        # ShapeInput (2), ShapeSet (0), Unsorted (0)
        xext.XShapeCombineRectangles(display, xid, 2, 0, 0, rects, 1 if rects else 0, 0, 0)
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)
    return True


def set_empty_input_shape(xid: int, x11: Any = None, xext: Any = None) -> bool:
    """Give window `xid` an empty X input shape so every click falls through it; True on success."""
    return set_input_shape(xid, None, x11, xext)


def parse_mode(raw: str, width: int = WINDOW_WIDTH, height: int = WINDOW_HEIGHT) -> Rect | None:
    """The card rectangle (device pixels) the page asked to take input over, or None for none.

    Anything malformed means none: the window stays click-through, so a bad message can never
    leave an invisible window swallowing the user's clicks.
    """
    try:
        message = json.loads(raw)
        if not isinstance(message, dict) or message.get("interactive") is not True:
            return None
        x, y, w, h = (float(v) for v in message["rect"])
        scale = float(message.get("scale", 1))
    except (ValueError, TypeError, KeyError):
        return None
    if not (0 < scale <= 8) or w <= 0 or h <= 0:
        return None
    left, top = max(0, int(x * scale)), max(0, int(y * scale))
    # X input shapes are in device pixels, so the window's size is scaled too
    right = min(int(width * scale), int((x + w) * scale + 0.999))
    bottom = min(int(height * scale), int((y + h) * scale + 0.999))
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def _load_gtk() -> tuple[Any, Any, Any, Any]:
    """Import gi and GTK 3 / WebKit2 4.1, raising GuiUnavailable on failure."""
    try:
        import gi  # noqa: PLC0415 - lazy: the module must import without gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkX11", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import (  # noqa: PLC0415
            Gdk,
            GdkX11,  # noqa: F401
            GLib,
            Gtk,
            WebKit2,
        )
    except (ImportError, ValueError) as error:
        raise GuiUnavailable(str(error)) from error
    return Gdk, GLib, Gtk, WebKit2


def _make_window(gtk: Any, gdk: Any) -> Any:
    """Create and configure the borderless, click-through HUD window."""
    win = gtk.Window(type=gtk.WindowType.TOPLEVEL)
    win.set_title("Jarvis HUD")
    win.set_decorated(False)
    win.set_keep_above(True)
    win.set_skip_taskbar_hint(True)
    win.set_skip_pager_hint(True)
    win.set_accept_focus(False)
    win.set_focus_on_map(False)
    win.set_type_hint(gdk.WindowTypeHint.NOTIFICATION)
    win.set_app_paintable(True)
    win.stick()
    visual = win.get_screen().get_rgba_visual()
    if visual is not None:
        win.set_visual(visual)
    win.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    return win


def _make_view(webkit: Any, gdk: Any) -> Any:
    """Create the transparent, non-focusable WebKit2 view."""
    view = webkit.WebView()
    view.set_background_color(gdk.RGBA(0, 0, 0, 0))
    view.set_can_focus(False)
    return view


def _position_window(win: Any, gdk: Any) -> None:
    """Show the window, move it to the top-centred, bottom slot, and make it click-through."""
    display = gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    area = monitor.get_workarea()
    win.show_all()
    x, y = placement((area.x, area.y, area.width, area.height), WINDOW_WIDTH, WINDOW_HEIGHT)
    win.move(x, y)
    xid = win.get_window().get_xid()
    if not set_empty_input_shape(xid):
        print("jarvis hud: could not make the window click-through", file=sys.stderr)


def _follow_page(win: Any, view: Any, gdk: Any) -> None:
    """Switch between click-through and taking input over the card, as the page says (R82)."""
    manager = view.get_user_content_manager()
    manager.register_script_message_handler("hud")

    def on_message(_manager: Any, result: Any) -> None:
        rect = parse_mode(result.get_js_value().to_string())
        xid = win.get_window().get_xid()
        set_input_shape(xid, rect)
        win.set_accept_focus(rect is not None)
        view.set_can_focus(rect is not None)
        if rect is not None:
            win.present_with_time(gdk.CURRENT_TIME)
            view.grab_focus()

    manager.connect("script-message-received::hud", on_message)


def _run(url: str, token: str, gui: tuple[Any, Any, Any, Any]) -> int:
    """Build the window, load the page and run the GTK main loop."""
    gdk, glib, gtk, webkit = gui
    parent = os.getppid()
    win = _make_window(gtk, gdk)
    view = _make_view(webkit, gdk)
    win.add(view)
    _position_window(win, gdk)
    _follow_page(win, view, gdk)

    def quit_loop() -> bool:
        gtk.main_quit()
        return bool(glib.SOURCE_REMOVE)

    def parent_check() -> bool:
        if os.getppid() == parent:
            return bool(glib.SOURCE_CONTINUE)
        return quit_loop()

    win.connect("destroy", lambda *_: gtk.main_quit())
    glib.unix_signal_add(glib.PRIORITY_DEFAULT, signal.SIGTERM, quit_loop)
    glib.unix_signal_add(glib.PRIORITY_DEFAULT, signal.SIGINT, quit_loop)
    glib.timeout_add_seconds(1, parent_check)
    view.load_uri(page_url(url, token))
    gtk.main()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point: validate token, load GTK, then run the HUD window."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    token = os.environ.pop(TOKEN_ENV, "")  # WebKit helper processes must not inherit it
    if not token:
        print("jarvis hud: JARVIS_HUD_TOKEN is not set", file=sys.stderr)
        return EXIT_USAGE
    try:
        gui = _load_gtk()
    except GuiUnavailable as error:
        print(f"jarvis hud: GTK 3 / WebKit2 4.1 are not available: {error}", file=sys.stderr)
        return EXIT_NO_GUI
    ok, _ = gui[2].init_check()
    if not ok:
        print("jarvis hud: cannot open the display", file=sys.stderr)
        return EXIT_NO_GUI
    return _run(args.url, token, gui)


if __name__ == "__main__":
    sys.exit(main())
