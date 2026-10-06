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

Probe: `spikes/M0c-desktop-control/x11_probe.py`, run with the system Python (PyGObject: Wnck, Atspi, Gio, Gdk/GdkX11). No root and no extra packages (`xdotool`, `python-xlib` and `ydotool` are not installed). The probe prints only counts and timings, never window titles or UI text. The active phase acts only on a window it launched itself.

| Capability | Method | Success | p50 | max |
|---|---|---|---|---|
| List windows | Wnck | 10/10 (×5 runs) | ~0 ms | 98 ms |
| Read UI tree | AT-SPI | 10/10 (×5 runs) | 10–13 ms | 79 ms |
| Full-screen screenshot | Gdk root window | 10/10 (×5 runs) | 67–72 ms | 116 ms |
| Launch app and identify its new window | Gio + window-id diff | 1/1 | 430 ms | — |
| Focus own window | Wnck `activate` | 10/10 | 203 ms* | 206 ms |
| Insert text into own empty field | AT-SPI EditableText | 10/10 in the clean run | 97 ms | 118 ms |
| Close own window | Wnck `close` | 1/1 | — | — |
| Press a key | AT-SPI `generate_keyboard_event` | **0/2: process segfaulted** | — | — |

\* includes a fixed 200 ms settle wait; the real focus time is lower.

**Stability:** read-only capabilities were stable across every run (5 runs, plus 3 extra read-only runs, 0 crashes). The **active phase completed cleanly in 1 of 4 runs**. In the other 3, the probe process segfaulted inside AT-SPI text or keyboard calls on GTK4 Calculator. The log shows `AT-SPI: Error in GetItems … /org/a11y/atspi/cache` (GTK4 does not provide the AT-SPI cache interface). `toolkit-accessibility` is `false` on this machine; GTK4 apps exposed their tree anyway.

**Findings that change the design:**
1. **Single-instance apps reuse their process.** Launching GNOME Text Editor while it was already running brought the existing window forward and created no new process. "Launch" must identify windows by diffing the window list, not by PID. "Already running" means focus it (FR-PC-01/02).
2. **AT-SPI write operations can crash the calling process.** Accessibility automation must run in a separate worker process that is restarted on a crash, never inside jarvisd (FR-LIFE-01, policy-gate integrity).
3. Simulating key presses through AT-SPI is not reliable from Python here. Evaluate **XTest** (`python-xlib`, or `xdotool`) and **clipboard + paste** for typing in the next round. Both need a new dependency (owner approval).
4. A launched app inherits the launcher's stdout/stderr. jarvisd must launch apps fully detached, with fds closed, or the launcher stays tied to the app.

## Result — part 2: GNOME Wayland

_Pending: needs the owner to log in to "Ubuntu on Wayland" once._

## Decision (part 1)

**X11: GO** for launch, list, focus, read UI and screenshot through Wnck + AT-SPI + Gio + Gdk, with no root.
**X11 input (type and keys): NOT YET.** AT-SPI insert works but crashes intermittently, and key synthesis crashed 2/2. Next: compare XTest against clipboard-paste inside an isolated worker process.

The Wayland result and the final M0c decision come after part 2.
