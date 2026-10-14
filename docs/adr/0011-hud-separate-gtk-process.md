# 0011 — The HUD is a separate GTK/WebKit process, not pywebview

- **Status:** Accepted (2026-10-14)
- **Deciders:** @nikhilm55
- **Refs:** FRS §5.16 FR-UI-01, §9.1–9.2; ADR-0008 (isolation), ADR-0010; M1 task 12

## Context

FRS §9.2 planned a pywebview frameless, transparent, always-on-top window for the HUD. On Linux, pywebview's GTK backend needs PyGObject (`gi`), which the project's uv virtualenv cannot import; the system Python 3.12 on GNOME has `gi` with GTK 3 and WebKit2 4.1. A GUI toolkit crash inside jarvisd would also take down the voice loop and the policy gate.

## Options

1. pywebview inside jarvisd, with `--system-site-packages` or PyQt/WebEngine wheels (≈ 100+ MB).
2. A separate HUD process under the system Python using `gi` directly (GTK3 window + WebKit2 view), fed by a loopback SSE server in jarvisd.

## Decision

Option 2. `src/jarvis/hud/window.py` imports only the standard library and `gi`, runs under `/usr/bin/python3` (configurable: `Settings.hud.python`), shows a frameless, always-on-top, click-through (empty X input shape), non-focus-stealing window, and loads `/hud` from jarvisd's `HudServer` (Starlette on 127.0.0.1, same Host + bearer guard as the MCP server; token in the URL fragment, never argv). jarvisd supervises it with backoff and runs headless if it can't start.

## Consequences

- Easier: no heavy GUI dependency in the venv; a HUD crash never affects jarvisd (same spirit as ADR-0008).
- Harder: the HUD depends on the system Python having GTK3 + WebKit2 4.1 — packaging (M4) must check or provide it; the window is X11-only today (Wayland is deferred, ADR-0009).
- The main window and setup wizard (M4) are still open: pywebview may be revisited there.
