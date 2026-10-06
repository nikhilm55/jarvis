# 0001 — Record architecture decisions

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** AI Academy (docs folder, memory system)

## Context

Decisions made in chat are lost on the next session reset, and agents re-litigate them.

## Options

1. Decisions live only in the FRS: one place, but the FRS mixes requirements with their rationale.
2. Numbered ADRs in `docs/adr/`, linked from the FRS and `AGENTS.md`.

## Decision

Record every hard-to-reverse decision as a numbered ADR using `0000-template.md`. The `adr` skill guides agents through it. Accepted ADRs are never rewritten; they are superseded.

## Consequences

- Easier: agents and new contributors find the *why* without chat history.
- Harder: one more file per decision.
- Must be true: every ADR has Context, Options, Decision, Consequences; CI checks links.
