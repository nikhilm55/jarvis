# 0007 — "Jarvis" must be the first word

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** FRS §5.1, D1, D9

## Context

Commands are spoken as one phrase ("Jarvis, open Teams"). "Jarvis" said mid-sentence or on TV must not trigger anything.

## Options

1. Wake-word engine only: false triggers mid-sentence.
2. Wake word + ≥ 400 ms silence before it + STT first-word check + pre-roll buffer.

## Decision

Adopt option 2, using openWakeWord with a custom "Jarvis" model (Porcupine as fallback). Follow-up answers inside a visible 8 s window are the only exemption. Spike M0a validates accuracy.

## Consequences

- Easier: natural one-breath commands; few false triggers.
- Harder: needs custom wake-model training and calibration.
- Must be true: the gate drops any utterance whose transcript doesn't start with a Jarvis variant.
