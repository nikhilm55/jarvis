# 0003 — Claude Code as the default brain, with its own MCP config

- **Status:** Accepted (2026-10-06)
- **Deciders:** @nikhilm55
- **Refs:** FRS §5.5, D2

## Context

The owner already uses Claude Code with a subscription, which needs no API key. Jarvis must also never pollute the user's personal Claude config.

## Options

1. Claude Code headless (stream-json), warm session, with Jarvis's own `--mcp-config --strict-mcp-config` and `--settings`.
2. API-only brains: needs keys and Jarvis's own agent loop for every user.
3. Write Jarvis servers into `~/.claude.json`: they leak into coding sessions and risk config corruption.

## Decision

Default to option 1. API and OpenAI-compatible URL brains are supported through Jarvis's own agent loop with the same contract and policy gate.

## Consequences

- Easier: zero-key setup for Claude Code users.
- Harder: distributing a product that drives a consumer subscription needs a terms check (OQ-003).
- Must be true: Jarvis never writes `~/.claude.json`; the brain never runs with bypass permission flags. The policy gate decides through hooks.
