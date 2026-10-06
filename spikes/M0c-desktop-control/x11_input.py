"""M0c input probe (X11): XTest keystrokes via ctypes (no new deps), each step in a separate worker process.

Run with the SYSTEM python: /usr/bin/python3 spikes/M0c-desktop-control/x11_input.py [--app org.gnome.Calculator.desktop]
Launches its OWN window of an app that is not running, and sends keys only while that window is active.
Never touches the clipboard. Prints counts and timings only (and the digits it typed into its own window).
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import os
import statistics
import subprocess
import sys
import time

HERE = __file__
TRIALS = 10
TEXT = "1234"


# ── worker: XTest typing (runs in its own process) ─────────────────────────
def xtest_keys(keysyms: list[str]) -> int:
    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xtst = ctypes.CDLL(ctypes.util.find_library("Xtst"))
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        return 2
    for name in keysyms:
        code = x11.XKeysymToKeycode(display, x11.XStringToKeysym(name.encode()))
        if not code:
            return 3
        xtst.XTestFakeKeyEvent(display, code, 1, 0)
        xtst.XTestFakeKeyEvent(display, code, 0, 0)
    x11.XFlush(display)
    return 0


# ── worker: read the display text of the active frame of pid via AT-SPI ────
def atspi_read(pid: int) -> int:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    Atspi.set_timeout(2000, 15000)
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is None or app.get_process_id() != pid:
            continue
        for j in range(app.get_child_count()):
            frame = app.get_child_at_index(j)
            if frame is None or not frame.get_state_set().contains(Atspi.StateType.ACTIVE):
                continue
            stack = [frame]
            while stack:
                node = stack.pop()
                if node.get_role() == Atspi.Role.TEXT and node.get_state_set().contains(
                    Atspi.StateType.EDITABLE
                ):
                    text = node.get_text_iface()
                    print(Atspi.Text.get_text(text, 0, Atspi.Text.get_character_count(text)))
                    return 0
                stack.extend(
                    node.get_child_at_index(k) for k in range(min(node.get_child_count(), 50))
                )
    return 4


# ── orchestrator ───────────────────────────────────────────────────────────
def worker(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, HERE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="org.gnome.Calculator.desktop")
    parser.add_argument("--worker-keys", nargs="*")
    parser.add_argument("--worker-read", type=int)
    args = parser.parse_args()
    if args.worker_keys is not None:
        return xtest_keys(args.worker_keys)
    if args.worker_read is not None:
        return atspi_read(args.worker_read)

    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkX11", "3.0")
    gi.require_version("Gio", "2.0")
    gi.require_version("Wnck", "3.0")
    from gi.repository import Gdk, GdkX11, Gio, GLib, Wnck

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            while GLib.MainContext.default().iteration(False):
                pass
            time.sleep(0.02)

    def windows() -> dict[int, Wnck.Window]:
        screen = Wnck.Screen.get_default()
        screen.force_update()
        return {w.get_xid(): w for w in screen.get_windows()}

    before = set(windows())
    Gio.DesktopAppInfo.new(args.app).launch([], Gdk.Display.get_default().get_app_launch_context())
    window = None
    for _ in range(100):
        pump(0.1)
        fresh = set(windows()) - before
        if fresh:
            window = windows()[fresh.pop()]
            break
    if window is None:
        print("launch failed")
        return 1
    pid = window.get_pid()
    now = lambda: GdkX11.x11_get_server_time(Gdk.get_default_root_window())  # noqa: E731

    typed_ok, cleared_ok, crashes, latencies = 0, 0, 0, []
    for _ in range(TRIALS):
        window.activate(now())
        pump(0.3)
        if not window.is_active():
            continue  # never send keys unless our own window is focused
        start = time.perf_counter()
        code, _ = worker("--worker-keys", *TEXT)
        latencies.append((time.perf_counter() - start) * 1000)
        pump(0.2)
        code_r, shown = worker("--worker-read", str(pid))
        crashes += code_r < 0
        typed_ok += code == 0 and shown == TEXT
        if window.is_active():
            worker("--worker-keys", *(["BackSpace"] * len(TEXT)))
        pump(0.2)
        code_r, shown = worker("--worker-read", str(pid))
        crashes += code_r < 0
        cleared_ok += code_r == 0 and shown == ""
    window.close(now())
    pump(1.5)
    closed = window.get_xid() not in windows()
    print("| Capability | success | p50 | max |\n|---|---|---|---|")
    print(
        f"| type '{TEXT}' via XTest worker, verified via AT-SPI worker | {typed_ok}/{TRIALS} | {statistics.median(latencies):.0f} ms | {max(latencies):.0f} ms |"
    )
    print(f"| delete via XTest BackSpace, verified empty | {cleared_ok}/{TRIALS} | — | — |")
    print(f"| AT-SPI reader worker crashes | {crashes}/{2 * TRIALS} | — | — |")
    print(f"| close own window | {int(closed)}/1 | — | — |")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # libwnck/PyGObject can segfault while finalising wrappers of closed windows: skip finalisers.
    os._exit(code)
