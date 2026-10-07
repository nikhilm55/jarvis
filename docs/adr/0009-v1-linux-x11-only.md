# 0009 — v1 on Linux targets GNOME on X11; Wayland later

- **Status:** Accepted (2026-10-07)
- **Deciders:** @nikhilm55
- **Refs:** FRS D15, D17, §7.5, §9.3; M0c

## Context

M0c proved every v1 desktop capability on GNOME 46 X11 without root. Wayland restricts global input injection, always-on-top overlays and global hotkeys, and needs portals, `ydotool`/uinput and compositor extensions. That part was never measured. The owner runs X11 and chose to skip the Wayland spike.

## Options

1. Support X11 and Wayland in v1: wider reach, but an unmeasured risk and a larger M1–M2.
2. v1 = GNOME on X11. Detect Wayland and explain how to switch; Wayland becomes its own milestone.

## Decision

Option 2. At startup and in the setup wizard, a Wayland session is detected (`XDG_SESSION_TYPE`). Jarvis explains that v1 needs "Ubuntu on Xorg" and how to select it at login, instead of failing silently.

## Consequences

- Easier: one display stack to build and test for M1–M3.
- Harder: on stock Ubuntu 24.04 (Wayland by default), new users must switch session once.
- Must be true: platform code stays behind interfaces (ADR-0002), so a Wayland backend can be added later; M0c part 2 is that milestone's first task.
