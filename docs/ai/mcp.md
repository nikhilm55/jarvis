# MCP servers and plugins — inventory

Project-scope servers for **developing** Jarvis (not the product's runtime MCP catalog, which is FRS Appendix A). Config: `.mcp.json`. Enabled by name in `.claude/settings.json` → `enabledMcpjsonServers`.

| Server | Purpose | Why not a CLI | Publisher / source | Version | Transport | Credentials | Scope | Owner |
|---|---|---|---|---|---|---|---|---|
| `context7` | Current library docs for fast-moving deps (openWakeWord, faster-whisper, pywebview, MCP SDK) when training data is stale | No CLI gives version-specific docs inside the agent's context | Upstash (`@upstash/context7-mcp`, github.com/upstash/context7) | **4.1.1** (pinned) | stdio (local `npx`) | None (optional `CONTEXT7_API_KEY` from env, never in config) | Read-only: resolves library IDs and fetches docs; no write tools | @nikhilm55 |

**Not used, and why:**
- GitHub MCP: the `gh` CLI covers it, with read-only commands pre-allowed.
- Browser MCPs (Playwright, Chrome DevTools): out of scope for now (owner decision, 2026-10-06).
- Filesystem MCP: Claude Code's built-in tools already cover the repo.

**Plugins:** none at project scope. Personal plugins (e.g. superpowers) are user-scope and uncommitted. Read a plugin's source before installing it.

**Upgrade procedure:** a Dependabot-style manual bump. Read the changelog, update the pinned version here and in `.mcp.json` in the same PR, and get the owner's review.
