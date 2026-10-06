@AGENTS.md

## Claude Code specifics

- Hooks in `.claude/settings.json` enforce the rules above: destructive or review-bypassing commands are blocked, edits to agent/CI config ask for approval, Python files are auto-formatted, and the Stop hook runs ruff, mypy and pytest. A blocked call explains why. Fix the cause; never work around a hook.
- The sandbox (bubblewrap + socat on Linux) limits network access to the allowlist in `.claude/settings.json`. If you need another domain, ask; don't route around the sandbox.
- MCP: only `context7` (library docs). Say "use context7" when you need current docs for a fast-moving library.
- Personal overrides go in `CLAUDE.local.md` or `.claude/settings.local.json`. Both are gitignored; never commit them.
