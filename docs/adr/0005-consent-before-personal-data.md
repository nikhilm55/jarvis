# 0005 — Consent before touching personal data

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** FRS §5.11, D11–D14

## Context

Users only trust an AI with their messages, files and screen if it asks first, and only approved things are touched.

## Options

1. Risk tiers only: they cover actions but not reading private data.
2. A separate consent layer with per-scope grants (once / session / always / never), answered by voice or typing.

## Decision

Adopt the consent layer, enforced by the policy gate. YOLO skips prompts but still respects "never" and deny lists. No answer means no.

## Consequences

- Easier: a clear privacy story; grants are auditable.
- Harder: every tool must declare its data scopes.
- Must be true: outside YOLO, zero personal-source access without a matching grant (release gate, FRS §7.8).
