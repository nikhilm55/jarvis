"""M0c probe: desktop-control capabilities on the current GNOME session, no root, no extra packages.

Run with the SYSTEM python (needs PyGObject): /usr/bin/python3 spikes/M0c-desktop-control/x11_probe.py
Read-only by default. `--act` also launches its own window of an app that is not already running (default: Calculator), focuses it, inserts
text through AT-SPI (no synthetic keystrokes) and closes it — it never touches other windows.
Prints only counts and timings, never window titles or UI text (they are the user's data).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Atspi", "2.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Atspi, Gdk, GdkX11, Gio, GLib, Wnck  # noqa: E402

TRIALS = 10
Atspi.set_timeout(2000, 15000)  # never block forever on an unresponsive app
MARKER = "jarvis-m0c-probe"


def timed(fn: Callable[[], object], trials: int = TRIALS) -> tuple[int, float, float]:
    """Run fn `trials` times; return (successes, p50 ms, max ms)."""
    name = getattr(fn, "__name__", "step")
    print(f"  … {name}", file=sys.stderr, flush=True)
    ok, times = 0, []
    for _ in range(trials):
        start = time.perf_counter()
        try:
            if fn():
                ok += 1
        except Exception as exc:  # spike: record, don't crash
            print(f"  error: {type(exc).__name__}", file=sys.stderr)
        times.append((time.perf_counter() - start) * 1000)
    print(
        f"  = {name}: {ok}/{trials}, p50 {statistics.median(times):.0f} ms",
        file=sys.stderr,
        flush=True,
    )
    return ok, statistics.median(times), max(times)


def pump(seconds: float = 0.0) -> None:
    end = time.monotonic() + seconds
    while True:
        while GLib.MainContext.default().iteration(False):
            pass
        if time.monotonic() >= end:
            return
        time.sleep(0.02)


def list_windows() -> bool:
    screen = Wnck.Screen.get_default()
    screen.force_update()
    return len(screen.get_windows()) > 0


def atspi_read() -> bool:
    desktop = Atspi.get_desktop(0)
    nodes = 0
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is None:
            continue
        nodes += 1 + app.get_child_count()
    return nodes > 0


def screenshot() -> bool:
    root = Gdk.get_default_root_window()
    pixbuf = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shot.png"
        pixbuf.savev(str(path), "png", [], [])
        return path.stat().st_size > 0  # file deleted with the temp dir; never opened


def window_ids() -> set[int]:
    screen = Wnck.Screen.get_default()
    screen.force_update()
    return {w.get_xid() for w in screen.get_windows()}


def window_by_xid(xid: int) -> Wnck.Window | None:
    screen = Wnck.Screen.get_default()
    screen.force_update()
    return next((w for w in screen.get_windows() if w.get_xid() == xid), None)


def own_empty_text(pid: int) -> Atspi.Accessible | None:
    """The editable text of the ACTIVE frame of `pid`, only if it is empty (a brand-new document)."""
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app_node = desktop.get_child_at_index(i)
        if app_node is None or app_node.get_process_id() != pid:
            continue
        for j in range(app_node.get_child_count()):
            frame = app_node.get_child_at_index(j)
            if frame is None or not frame.get_state_set().contains(Atspi.StateType.ACTIVE):
                continue
            stack = [frame]
            while stack:
                node = stack.pop()
                states = node.get_state_set()
                if node.get_role() == Atspi.Role.TEXT and states.contains(Atspi.StateType.EDITABLE):
                    text = node.get_text_iface()
                    return node if text is not None and text.get_character_count() == 0 else None
                stack.extend(
                    node.get_child_at_index(k) for k in range(min(node.get_child_count(), 50))
                )
    return None


def act(desktop_id: str, keys: bool) -> list[tuple[str, tuple[int, float, float]]]:
    """Launch → identify the NEW window by diffing window ids (single-instance apps reuse their process)."""
    results = []
    app = Gio.DesktopAppInfo.new(desktop_id)
    before = window_ids()
    new_xid: list[int] = []

    def launch() -> bool:
        context = Gdk.Display.get_default().get_app_launch_context()
        app.launch([], context)
        for _ in range(100):  # wait up to ~10 s for a window that did not exist before
            pump(0.1)
            fresh = window_ids() - before
            if fresh:
                new_xid.append(fresh.pop())
                return True
        return False

    results.append(("launch app (Gio) + new window identified", timed(launch, 1)))
    window = window_by_xid(new_xid[0]) if new_xid else None
    if window is None:
        return results
    pid = window.get_pid()

    def focus() -> bool:
        window.activate(GdkX11.x11_get_server_time(Gdk.get_default_root_window()))
        pump(0.2)
        return window.is_active()

    results.append(("focus own window (Wnck)", timed(focus)))

    def insert_and_clear() -> bool:
        if not window.is_active():
            return False  # never type unless our own window is the active one
        node = own_empty_text(pid)
        if node is None:
            return False  # not provably our empty document: refuse
        editable = node.get_editable_text_iface()
        inserted = bool(editable.insert_text(0, MARKER, -1))
        editable.delete_text(0, len(MARKER))
        return inserted

    results.append(("insert text via AT-SPI (own empty doc)", timed(insert_and_clear)))

    def press_key() -> bool:
        """Synthesise one keypress ('7') only while OUR window is active, then read it back."""
        if not window.is_active():
            return False
        node = own_empty_text(pid)
        if node is None:
            return False
        Atspi.generate_keyboard_event(Gdk.KEY_7, None, Atspi.KeySynthType.SYM)
        pump(0.15)
        text = node.get_text_iface()
        got = Atspi.Text.get_text(text, 0, Atspi.Text.get_character_count(text)) if text else ""
        editable = node.get_editable_text_iface()
        if editable and got:
            editable.delete_text(0, len(got))
        return got == "7"

    if keys:  # opt-in: segfaulted PyGObject 2/2 runs on GNOME 46 X11 (see the card)
        results.append(("press key via AT-SPI synth (own window)", timed(press_key)))
    window.close(GdkX11.x11_get_server_time(Gdk.get_default_root_window()))
    pump(1.5)
    results.append(("close own window", (int(window_by_xid(new_xid[0]) is None), 0.0, 0.0)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--act", action="store_true", help="also launch/focus/type/close an own app window"
    )
    parser.add_argument(
        "--keys", action="store_true", help="also synthesise one keypress (crashed on GNOME 46 X11)"
    )
    parser.add_argument(
        "--app",
        default="org.gnome.Calculator.desktop",
        help="desktop id of an app that is NOT running",
    )
    args = parser.parse_args()
    print(
        f"session={os.environ.get('XDG_SESSION_TYPE')} desktop={os.environ.get('XDG_CURRENT_DESKTOP')}"
    )
    rows = [
        ("list windows (Wnck)", timed(list_windows)),
        ("read UI tree (AT-SPI)", timed(atspi_read)),
        ("full-screen screenshot (Gdk)", timed(screenshot)),
    ]
    if args.act:
        rows += act(args.app, args.keys)
    print("| Capability | success | p50 | max |\n|---|---|---|---|")
    for name, (ok, p50, worst) in rows:
        n = 1 if name.startswith(("launch", "close")) else TRIALS
        print(f"| {name} | {ok}/{n} | {p50:.0f} ms | {worst:.0f} ms |")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # libwnck/PyGObject can segfault while finalising wrappers of closed windows: skip finalisers.
    os._exit(code)
