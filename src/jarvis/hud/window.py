"""Standalone HUD window process.

Runs as a separate process under the system python 3.12 with stdlib and gi
(PyGObject) only; it never imports the jarvis package or third-party code.
Exit codes: 0 normal, 2 no token, 78 no GUI. The window exits when its
parent process dies or on SIGTERM/SIGINT. The token arrives in the
environment (never argv) and reaches the page only in the URL fragment.
"""

import argparse
import os
import signal
import sys
import urllib.parse
from typing import Any

EXIT_NO_GUI = 78
EXIT_USAGE = 2
TOKEN_ENV = "JARVIS_HUD_TOKEN"  # noqa: S105 - the variable name, not a secret
TITLE_PREFIX = "Jarvis HUD:"
WINDOW_WIDTH = 612
WINDOW_HEIGHT = 140


class GuiUnavailable(Exception):
    """Raised when GTK 3 / WebKit2 4.1 cannot be loaded."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments requiring a --url option."""
    parser = argparse.ArgumentParser(prog="window.py")
    parser.add_argument("--url", required=True)
    return parser.parse_args(argv)


def visible_from_title(title: str | None) -> bool | None:
    """Map a page title to a visibility flag or None for unknown titles."""
    if title is None:
        return None
    if title == f"{TITLE_PREFIX}visible":
        return True
    if title == f"{TITLE_PREFIX}hidden":
        return False
    return None


def placement(area: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int]:
    """Compute the top-centred, bottom-aligned window position for an area."""
    ax, ay, aw, ah = area
    return ax + (aw - width) // 2, ay + ah - height


def page_url(url: str, token: str) -> str:
    """Append the token to the url as a quoted URL fragment."""
    return f"{url}#{urllib.parse.quote(token, safe='')}"


def _load_gtk() -> tuple[Any, Any, Any, Any]:
    """Import gi and GTK 3 / WebKit2 4.1, raising GuiUnavailable on failure."""
    try:
        import gi  # noqa: PLC0415 - lazy: the module must import without gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: PLC0415
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
    """Show the window and move it to the top-centred, bottom slot."""
    display = gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    area = monitor.get_workarea()
    win.show_all()
    x, y = placement((area.x, area.y, area.width, area.height), WINDOW_WIDTH, WINDOW_HEIGHT)
    win.move(x, y)
    win.get_window().set_pass_through(True)


def _on_title(view: Any, win: Any) -> None:
    """Toggle click-through based on the page title visibility flag."""
    flag = visible_from_title(view.get_title())
    if flag is None:
        return
    window = win.get_window()
    if window is None:
        return
    window.set_pass_through(not flag)


def _run(url: str, token: str, gui: tuple[Any, Any, Any, Any]) -> int:
    """Build the window, load the page and run the GTK main loop."""
    gdk, glib, gtk, webkit = gui
    parent = os.getppid()
    win = _make_window(gtk, gdk)
    view = _make_view(webkit, gdk)
    win.add(view)
    _position_window(win, gdk)

    def quit_loop() -> bool:
        gtk.main_quit()
        return bool(glib.SOURCE_REMOVE)

    def parent_check() -> bool:
        if os.getppid() == parent:
            return bool(glib.SOURCE_CONTINUE)
        return quit_loop()

    view.connect("notify::title", lambda v, _param: _on_title(v, win))
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
    token = os.environ.get(TOKEN_ENV, "")
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
