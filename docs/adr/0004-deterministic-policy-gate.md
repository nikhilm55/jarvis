# 0004 — The model decides, deterministic code executes

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** FRS §4.1, §5.6, §5.10, D3

## Context

An LLM controlling a whole PC must not be trusted to police itself, and its output shape must be predictable for speech and UI.

## Options

1. Prompt-only safety: simple, but bypassable by mistakes or injected content.
2. A deterministic policy gate plus a validated I/O contract in jarvisd.

## Decision

Every tool call passes one policy gate (risk tiers, modes, guardrails) in jarvisd. The brain communicates only through the validated I/O contract (`jarvis.respond` and the control tools).

## Consequences

- Easier: swapping brains never changes safety or output structure.
- Harder: every tool needs a declared tier and scopes.
- Must be true: no code path executes a tool without the gate.
