# 0002 — Python core, reusing beyondMeetings by copying

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** FRS §9, §10, D7, D8

## Context

beyondMeetings already solves setup and doctor checks, secrets, the transcribers, the installers and CI for Windows and Linux in Python.

## Options

1. Python core, with modules copied from beyondMeetings.
2. Rust/Tauri core: faster and smaller, but a full rewrite with none of the proven installers.
3. Depend on beyondMeetings as a library: couples two products' release cycles.

## Decision

Jarvis is a separate Python (≥ 3.11) product. It copies and adapts beyondMeetings modules and never imports beyondMeetings at runtime.

## Consequences

- Easier: proven installers, doctor framework and Windows lessons from day one.
- Harder: fixes must be ported by hand between the two repos.
- Must be true: no `import beyondmeetings` anywhere in `src/`.
