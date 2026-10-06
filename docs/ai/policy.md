# AI usage policy — Jarvis repository

**Owner:** @nikhilm55 · **Backup:** @nikhilmalhotra55 · **Reviewed:** 2026-10-06 · **Next review:** first Monday of each month (see §Review cadence)

This policy governs how AI coding agents are used to build Jarvis. It does not describe the product's own AI features (those are in `docs/FRS.md`).

## 1. Approved tools and accounts

| Tool | Status | Account |
|---|---|---|
| Claude Code (CLI / IDE) | **Approved, primary** | FiftyFive Technologies org account, or the owner's approved Claude subscription |
| Other agents (Codex, Gemini CLI, Cursor, Copilot, …) | Not approved for this repo yet | — |

- Only org-approved accounts may be used on this code. Personal free-tier accounts are not allowed.
- Adding a new agent tool needs a PR that updates this table and adds the tool's instruction pointer to `AGENTS.md`.

## 2. Data classes

| Class | Examples | Agents may… |
|---|---|---|
| **Public** | FRS, ADRs, code, synthetic fixtures | read and write |
| **Internal** | Spike results, benchmarks, design mockup | read and write; no upload outside the approved AI tools |
| **Secret** | API keys (Groq, Anthropic, OpenAI), OAuth tokens, `.env*`, keys, `~/.ssh`, `~/.aws`, `~/.config/gh` | **never read or write**. Enforced by permission deny rules, the sandbox `denyRead`, and the `guard_read`/`guard_write`/`guard_bash` hooks |
| **Restricted (personal)** | Real Jarvis user data: recordings, transcripts, messages, contacts, consent grants (`~/.local/share/jarvis`, `%LOCALAPPDATA%\jarvis`) | **never read**. Enforced by deny rules plus `guard_read`. Tests use synthetic data in `tests/fixtures/` only |

Test data must be synthetic. Use `example.com` addresses, invented names, and self-recorded or generated audio. Never commit production data, dumps or other people's voices.

## 3. MCP servers and plugins

- The project MCP inventory is `docs/ai/mcp.md`. Every server is listed with its purpose, owner, pinned version and scopes.
- Adding a server: PR updating `.mcp.json`, `docs/ai/mcp.md` and `enabledMcpjsonServers`. The source must be official or a reputable publisher, the version pinned exactly (no `@latest`), credentials from env or OAuth only, and scopes least-privilege.
- No blanket approval: `enableAllProjectMcpServers` stays off; servers are enabled by name.
- Plugins are personal (user scope) and are not committed. Read a plugin's or skill's source before installing it.

## 4. Dangerous modes and human-approval list

- Bypass mode is disabled for this project (`permissions.disableBypassPermissionsMode: "disable"`). Never run `--dangerously-skip-permissions` here.
- The sandbox is enabled (Linux, WSL and macOS) with a network allowlist. Unsandboxed escapes are disabled.
- **Always needs a human** (enforced by hooks, deny or ask rules): merging, approving or closing PRs · releases and tags · force-push · pushing to `main` · `sudo` · deleting repos · adding or removing dependencies (`uv add`/`uv remove`) · editing agent or CI config (`AGENTS.md`, `CLAUDE.md`, `.claude/**`, `.mcp.json`, `.github/**`, `.pre-commit-config.yaml`) · reading secrets · destructive deletes.

## 5. Review and attribution

- Every change reaches `main` through a PR with CI green and a human review using the PR template checklist. The author must be able to explain every line.
- AI review (the `code-review` skill) supplements human review and never replaces it.
- **Attribution:** commits written with an agent end with a `Co-Authored-By:` trailer naming the agent (Claude Code adds it by default), and the PR carries the `ai-assisted` label.
- New dependencies proposed by an agent are verified by a human: package name spelled correctly, real publisher, licence compatible, pinned in `uv.lock`. Dependabot and dependency review run in CI.

## 6. Licence and IP

- The repository licence is pending (OQ-004). Until then all code is © FiftyFive Technologies / the owner.
- Do not paste third-party code or docs into the repo beyond short quotations with attribution. Adapted material (e.g. skills from `FiftyfiveTech/claude-base-project-template`) names its source.
- AI-generated code is treated like human-written code: reviewed, tested and owned by the PR author.

## 7. Retention

- Local Claude Code transcripts are kept for 30 days (`cleanupPeriodDays: 30` in `.claude/settings.json`).
- Server-side retention follows the terms of the approved account type (org or commercial terms). Don't use consumer accounts that train on data for this repo.
- Prompt content is not exported to telemetry (`OTEL_LOG_USER_PROMPTS` stays unset; see `docs/ai/observability.md`).

## 8. Regulatory mapping

The product processes personal data (voice, messages, contacts) on the user's device.

| Concern | Where handled |
|---|---|
| GDPR / India DPDP: consent, purpose limitation, minimisation | FRS §5.11 (consent layer), §7.4 (privacy) |
| Right to erasure | FRS FR-LOG-03 (clear-all), FR-CON-12 (revoke) |
| Data sent to third parties (cloud STT/LLM) | FR-CON-15 disclosure, local-only mode |

No health, payment or children's data is in scope.

## 9. Review cadence

On the first Monday of each month, the owner reviews: `AGENTS.md` and the skills (still accurate?), permissions and hooks (still needed? any new bypass?), the MCP inventory (versions, scopes), `docs/ai/lessons.md` (promote repeated lessons into rules or hooks), and `docs/open-questions.md`. Each review is logged in `docs/ai/lessons.md` § Review log.
