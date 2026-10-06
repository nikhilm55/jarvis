# M0c — Can Jarvis reliably drive the Linux desktop (X11 and GNOME Wayland)?

**Hypothesis:** on GNOME 46 X11, every core desktop capability (launch, list/focus windows, type, press keys, read the UI via AT-SPI, screenshot) works without root. On GNOME Wayland, launch, AT-SPI read and screenshot (portal) work, while focus and input need ydotool or uinput plus a GNOME extension. Any gap is detectable, so Jarvis can explain it (FR-PC-21).
**FRS refs:** FR-PC-01…06, FR-PC-20/21, §9.3 capability matrix, FRS §12.1 Wayland risk.
**Method:**
1. Target apps: GNOME Text Editor, Settings, Chrome (Teams web as a stand-in).
2. For each capability × session (X11, then Wayland after re-login), run 10 trials and record success, latency and any permission prompt.
3. Candidates: xdotool/wmctrl (X11); AT-SPI via `pyatspi`/`gi` (both); `gnome-screenshot` / xdg-desktop-portal Screenshot (Wayland); ydotool (Wayland input, needs uinput access); GNOME Shell "window-calls" extension (Wayland window list and focus).
**Pass bar:** X11 has 6/6 capabilities at ≥ 95% success and ≤ 500 ms each. Wayland: launch, AT-SPI read and screenshot pass; for each of focus and input, either a working path or a clear, detectable limitation.
**Time-box:** 6 h (3 h X11, 3 h Wayland).

## Result

_Pending._

## Decision

_Pending._
