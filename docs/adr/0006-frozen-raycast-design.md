# 0006 — UI design frozen on the Raycast-derived system

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** FRS §8, D6, docs/design/jarvis-ui-mockup.html

## Context

The owner approved the mockup on 2026-10-06 and wants no later redesign churn.

## Options

1. Keep iterating the design during the build.
2. Freeze the approved mockup as the reference implementation target.

## Decision

The UI must match `docs/design/jarvis-ui-mockup.html`. Tokens, components and layout change only with the owner's sign-off and an updated mockup.

## Consequences

- Easier: no design drift; the agent builds from HTML, not screenshots.
- Harder: an improvement idea needs an explicit sign-off round.
- Must be true: UI code uses the token values from FRS §8.2 exactly.
