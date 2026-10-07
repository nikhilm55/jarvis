# 0008 — Desktop automation runs in an isolated worker, with EWMH for windows

- **Status:** Accepted (2026-10-07)
- **Deciders:** @nikhilm55
- **Refs:** M0c (`docs/spikes/M0c-desktop-control.md`), FRS §5.8, FR-LIFE-01

## Context

M0c proved every core desktop capability on GNOME 46 X11: launch, list, focus, read the UI, screenshot, type, press keys and close. But the Python process segfaulted while libwnck/PyGObject tore down wrappers for windows that had already closed: in 3/3 runs of the probe, and in 7 of 14 runs of the XTest orchestrator. Single-instance apps also reuse their process, so a launched window can't be found by PID.

## Options

1. Run the native bindings (Wnck, AT-SPI, XTest) inside jarvisd: simplest, but a native crash takes down the daemon, including the policy gate.
2. Run them in a separate **automation worker** process that jarvisd supervises; use EWMH over Xlib/XCB for window management instead of libwnck.

## Decision

All desktop automation runs in a supervised worker process. It reports each result as soon as it has it, and is restarted on a crash. Window management uses EWMH (`_NET_CLIENT_LIST`, `_NET_ACTIVE_WINDOW`, `_NET_CLOSE_WINDOW`), not libwnck. AT-SPI is used for reading the UI and inserting text (it handles non-ASCII); XTest for key combinations. Launched windows are identified by diffing the window list before and after launch, and apps are launched fully detached.

## Consequences

- Easier: a native crash costs one tool call (retried), never the daemon or the policy gate.
- Harder: an IPC boundary between jarvisd and the worker; tool latency rises by a few ms.
- Must be true: jarvisd never imports Wnck, AT-SPI or XTest bindings; every worker call has a timeout.
