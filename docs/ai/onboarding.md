# Onboarding — AI tooling for Jarvis

Takes about 15 minutes. You get the same agent behaviour, guardrails and skills as everyone else.

## 1. Prerequisites

| Tool | Linux | Windows |
|---|---|---|
| git | distro package | `winget install Git.Git` |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (read it first) | `winget install astral-sh.uv` |
| Node.js ≥ 18 (for the context7 MCP via `npx`) | distro package / nvm | `winget install OpenJS.NodeJS.LTS` |
| GitHub CLI | distro package | `winget install GitHub.cli` |
| Claude Code | official installer (docs.claude.com) | official installer |
| Sandbox deps (Linux only) | `sudo apt install bubblewrap socat` | — (sandbox is Linux/WSL/macOS only) |

Sign in to Claude Code with the **approved org account** (`docs/ai/policy.md` §1) and to `gh` with your GitHub account.

## 2. Clone to green

```
git clone <repo-url> && cd Jarvis
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pre-commit run --all-files
uv run mypy && uv run pytest -q
```

All green? Your setup matches CI.

## 3. First Claude Code session

1. Run `claude` in the repo root. Approve the `context7` MCP server when asked. It is the only project server.
2. Check that the guardrails work: ask the agent to run `git push --force`. The hook should block it and explain why.
3. Read `AGENTS.md` (it is the contract), then `docs/handoff.md` and `docs/open-questions.md`.
4. Try a skill: `/feature-development "<small task>"`, or `/spike M0a-wake-word`.

## 4. Personal settings

Put personal preferences in `CLAUDE.local.md` or `.claude/settings.local.json`. Both are gitignored. Never put shared rules there: shared rules go in `AGENTS.md` via a PR.

## 5. Where to learn more

- `docs/ai/workflow.md`: the loop, model choice, context budgets
- `docs/ai/policy.md`: data classes, approvals, attribution
- FiftyFive AI Academy: https://ai-assisted-learning.z89.ownkube.app/
