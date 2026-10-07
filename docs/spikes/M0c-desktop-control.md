# M0c — Can Jarvis reliably drive the Linux desktop (X11 and GNOME Wayland)?

**Hypothesis:** on GNOME 46 X11, every core desktop capability (launch, list/focus windows, type, press keys, read the UI via AT-SPI, screenshot) works without root. On GNOME Wayland, launch, AT-SPI read and screenshot (portal) work, while focus and input need ydotool or uinput plus a GNOME extension. Any gap is detectable, so Jarvis can explain it (FR-PC-21).
**FRS refs:** FR-PC-01…06, FR-PC-20/21, §9.3 capability matrix, FRS §12.1 Wayland risk.
**Method:**
1. Target apps: GNOME Text Editor, Settings, Chrome (Teams web as a stand-in).
2. For each capability × session (X11, then Wayland after re-login), run 10 trials and record success, latency and any permission prompt.
3. Candidates: xdotool/wmctrl (X11); AT-SPI via `pyatspi`/`gi` (both); `gnome-screenshot` / xdg-desktop-portal Screenshot (Wayland); ydotool (Wayland input, needs uinput access); GNOME Shell "window-calls" extension (Wayland window list and focus).
**Pass bar:** X11 has 6/6 capabilities at ≥ 95% success and ≤ 500 ms each. Wayland: launch, AT-SPI read and screenshot pass; for each of focus and input, either a working path or a clear, detectable limitation.
**Time-box:** 6 h (3 h X11, 3 h Wayland).

## Result — part 1: GNOME 46 on X11 (2026-10-06)

Probes, run with the system Python (PyGObject), no root and no new packages:
- `spikes/M0c-desktop-control/x11_probe.py`: Wnck, AT-SPI, Gio and Gdk/GdkX11.
- `spikes/M0c-desktop-control/x11_input.py`: XTest through `ctypes` on the system `libXtst`, with each typing and reading step in its own worker process.

Neither probe prints window titles or UI text. The active steps act only on a window the probe launched itself, and only after checking that it is active and its field is empty. Neither probe touches the clipboard.

| Capability | Method | Success | p50 | Runs |
|---|---|---|---|---|
| List windows | Wnck | 10/10 every run | ~0 ms | 11 |
| Read UI tree | AT-SPI | 10/10 every run | 10–24 ms | 11 |
| Full-screen screenshot | Gdk root window | 10/10 every run | 66–72 ms | 11 |
| Launch an app and identify its new window | Gio + window-id diff | 1/1 every run | 430–441 ms | 4 |
| Focus own window | Wnck `activate` | 10/10 every run | 203 ms* | 4 |
| Insert text into own empty field | AT-SPI EditableText | 10/10 every run | 97–109 ms | 4 |
| Press a key | AT-SPI `generate_keyboard_event` | 10/10 every run | 270 ms* | 3 |
| Type "1234", verified by reading back | XTest (`ctypes`) in a worker | 10/10 in every completed run | 73 ms | 7 |
| Delete with BackSpace, verified empty | XTest in a worker | 10/10 in every completed run | — | 7 |
| Close own window | Wnck `close` | 1/1 every run | — | 4 |

\* includes fixed settle waits (200 ms after focus, 150 ms after a key); the real latency is lower.

**Crash analysis (corrects the first draft of this card):** the probe process segfaults *after* its work is done, not during any operation. `python -X faulthandler` places every crash outside the operations, in two places:
- returning from the function that closed the window (`x11_probe.py`), when Python frees its Wnck/AT-SPI wrappers for the closed window;
- at interpreter exit (`x11_input.py`).

Printing results after every step shows every operation completed in every crashed run. Calling `Wnck.shutdown()` and exiting with `os._exit()` reduced but did not remove the crashes:
- the XTest orchestrator completed 7 of 14 runs;
- `x11_probe --act` crashed at teardown in 3/3 runs after all steps passed.

The cause is a libwnck/PyGObject lifetime bug around closed windows. It is not a limitation of the X11 desktop.

**Findings that change the design:**
1. **Single-instance apps reuse their process.** Launching GNOME Text Editor while it was already running brought the existing window forward and created no new process. "Launch" must identify windows by diffing the window list, not by PID. "Already running" means focus it (FR-PC-01/02).
2. **Run desktop automation in a separate worker process** that reports each result as soon as it has it, and is restarted if it dies. jarvisd must never host these native bindings in-process (FR-LIFE-01, policy-gate integrity).
3. **Don't build window management on libwnck from Python.** For M1, use EWMH over Xlib/XCB (`_NET_CLIENT_LIST`, `_NET_ACTIVE_WINDOW`) for list, focus and close. Keep AT-SPI for reading the UI and inserting text.
4. **Input:** use XTest for key combinations and plain ASCII. XTest can only type characters on the current keymap, so non-ASCII text (Hindi, emoji) goes through AT-SPI `insert_text` (10/10) or clipboard paste.
5. **A launched app inherits the launcher's stdout/stderr.** jarvisd must launch apps fully detached with fds closed, or the launcher stays tied to the app.

## Result — part 2: GNOME Wayland

**Skipped by owner decision (2026-10-07, FRS D17 / ADR-0009):** v1 targets GNOME on X11. Wayland moves to a later milestone, and its first task is this card's part-2 matrix.

## Decision (part 1)

**X11: GO for all core capabilities**: launch, list, focus, read UI, screenshot, type, keys and close. No root and no new packages (XTest via `ctypes`, AT-SPI and Gio/Gdk via the system PyGObject).
**Conditions:** an automation worker process (finding 2) and EWMH instead of libwnck for window management (finding 3).

The Wayland result and the final M0c decision come after part 2.
