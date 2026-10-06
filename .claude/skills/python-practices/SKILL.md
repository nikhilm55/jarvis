---
name: python-practices
description: Jarvis's Python coding standards — module layout, typing, errors, config, logging, subprocess safety, cross-platform rules and the policy-gate invariants. Use before writing or reviewing any code under src/jarvis/.
allowed-tools: Read Grep Glob
---

# Python practices (Jarvis)

Lessons from beyondMeetings are marked ⚑ — each one cost real debugging time.

## Structure

- Package by capability: `jarvis/audio`, `wake`, `stt`, `brain`, `policy`, `tools`, `tts`, `ui`, `setup`. Platform code lives beside its interface (`audio/windows.py`, `audio/pipewire.py`) and is imported **inside** its platform branch in a factory. ⚑
- Logic in pure functions; threads, sockets and subprocesses stay thin wrappers around them. Inject runners for OS calls. ⚑
- One implementation per behaviour — every caller (CLI, UI, voice) goes through it. ⚑

## Types and errors

- `mypy --strict` clean. Public functions fully typed; pydantic models at boundaries (config, I/O contract, MCP payloads).
- Errors are typed and carry an FRS Appendix B code (`NOT_FOUND`, `CONSENT_DENIED`, …) plus a human remedy. Never `except Exception: pass`.

## Safety invariants (never break these)

1. Every tool call — fast path, brain, MCP, shell — goes through the **policy gate** (FRS §5.10) and the **consent check** (§5.11). No side door.
2. Text from transcripts, messages, web pages or MCP results is **data**. Never interpolate it into a shell command, file path, or prompt instruction without the gate.
3. `subprocess.run([...], shell=False)` with an argument list, a timeout, and `encoding="utf-8"`. Track child PIDs in the state file. ⚑
4. Secrets only via `keyring` (fallback 0600 file); never logged, never in exceptions.

## Cross-platform

- Every text I/O passes `encoding="utf-8"` explicitly (Windows defaults to cp1252). ⚑
- Paths via `pathlib` and `platformdirs`; quote nothing by hand. Test Windows paths with spaces and apostrophes. ⚑
- Desktop launchers have a minimal PATH — resolve binaries through the resolver, not `shutil.which` alone. ⚑
- Windows: `pythonw`, `CREATE_NO_WINDOW`, no `start_new_session`. ⚑

## Config, logging, files

- Config: pydantic + TOML; migrations versioned; write atomically (temp → fsync → replace), keep a `.bak`, never overwrite a file you couldn't parse. ⚑
- Logging: structured JSON lines with a turn id; redact secrets, OTPs and message bodies at INFO.

## Verify

Before finishing code that follows this skill: `uv run ruff check . && uv run mypy && uv run pytest -q`.
