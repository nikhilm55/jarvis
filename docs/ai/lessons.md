# Lessons → rules (feedback loop)

When an agent makes the same mistake twice, record it here. If it can happen again, turn it into a rule (`AGENTS.md`), a skill step, or, best of all, a hook. Each entry links to where it now lives.

| Date | Lesson (what went wrong) | Became | Where |
|---|---|---|---|
| 2026-08 | One missing `encoding=` on a file containing `←` caused 168 Windows test failures (cp1252 default) — beyondMeetings | Rule 6 + review check | `AGENTS.md`, skill `python-practices`, skill `code-review` |
| 2026-08 | Two divergent stop paths (CLI vs app); only one compressed audio, so the app's Stop never worked — beyondMeetings | "One implementation per behaviour" | skill `python-practices` |
| 2026-08 | Desktop launchers have a minimal PATH, so agent CLIs installed via nvm or npm looked missing — beyondMeetings | Binary resolver rule | skill `python-practices`, FRS FR-BRN-11 |
| 2026-08 | A 13-day, 73 GB orphaned recorder process — beyondMeetings | Track child PIDs in one state file | skill `python-practices`, FRS FR-LIFE-01 |
| 2026-08 | Tests passed on substring checks while the real output was corrupted — beyondMeetings | "Evidence, not claims": read the real end-to-end output | skill `feature-development` |
| 2026-10-06 | A downloaded design reference and third-party text risk being committed wholesale | Third-party text stays out of the repo, linked instead | `docs/ai/policy.md` §6, `.gitignore` |
| 2026-10-07 | Under the Claude Code sandbox, 8 tests errored: a fixture copied whole folders, and the sandbox makes untracked agent-config paths under `.claude/` unreadable | Fixtures copy git-tracked files only (what CI sees) | `tests/test_ai_config.py` `repo` fixture |

## Review log

| Date | Reviewer | Notes |
|---|---|---|
| 2026-10-06 | @nikhilm55 | Initial setup: policy, hooks, permissions, sandbox, skills, MCP inventory. |
