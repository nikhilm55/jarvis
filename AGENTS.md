# Jarvis — agent instructions

Single source of truth for every AI coding agent in this repo. `CLAUDE.md` imports this file; do not duplicate its content elsewhere. Keep it under 150 lines — every line must prevent a mistake.

## Project

Jarvis is a Windows + Linux desktop app: say "Jarvis, …", Whisper transcribes it, an AI "brain" (default: the user's Claude Code, headless) acts on the PC through tools/MCP servers, and Jarvis speaks back. Spec: `docs/FRS.md`. **Current stage: M1 — the voice loop on Linux X11** (FRS §11, plan `docs/plans/2026-10-07-m1-voice-loop.md`, stack ADR-0010). Build only your assigned plan task; do not build ahead of the milestone.

## Stack (actual, not aspirational)

| Item | Version / choice |
|---|---|
| Python | ≥ 3.11 (dev on 3.12), package manager **uv** |
| Layout | `src/jarvis/` package, tests in `tests/` |
| Lint / format | ruff 0.16 (`pyproject.toml` `[tool.ruff]`) |
| Types | mypy 2.4 `--strict` |
| Tests | pytest 9 |
| Hooks | pre-commit (ruff, detect-secrets, hygiene) |
| Dev agent | Claude Code (project config in `.claude/`) |

Only libraries listed in `pyproject.toml` exist. Add one with `uv add <pkg>` (asks for approval) — never `pip install`.

## Commands

| Task | Command |
|---|---|
| Set up | `uv sync && uv run pre-commit install --hook-type pre-commit --hook-type pre-push` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| Type-check | `uv run mypy` |
| All tests | `uv run pytest -q` |
| One test | `uv run pytest tests/test_cli.py::test_should_exit_cleanly_when_run_without_arguments -q` |
| All pre-commit hooks | `uv run pre-commit run --all-files` |
| Validate AI config | `uv run python scripts/check_ai_config.py` |
| Run the CLI | `uv run jarvis --version` |

**Done means:** lint, format check, mypy and pytest all pass, with the real output shown.

## Where things are

| Path | What |
|---|---|
| `src/jarvis/` | Product code (package by capability — see skill `python-practices`) |
| `tests/` | pytest suite; `tests/fixtures/` synthetic data only |
| `docs/FRS.md` | Functional requirements — the spec for everything |
| `docs/architecture.md` | System overview, process model, component map |
| `docs/adr/` | Architecture decision records |
| `docs/open-questions.md` | Unresolved decisions (check at session start) |
| `docs/design/jarvis-ui-mockup.html` | **Frozen** approved UI design |
| `docs/plans/`, `docs/spikes/` | Milestone plans, spike cards and results |
| `docs/ai/` | AI policy, workflow, MCP inventory, observability, lessons |
| `docs/handoff.md` | Rolling session hand-off (DONE / NEXT / OPEN) |
| `.claude/` | Shared agent settings, hooks, skills |
| `scripts/check_ai_config.py` | CI validator for the AI setup |

## Rules

1. Work on a branch (`feat/…`, `fix/…`, `docs/…`, `chore/…`). Never commit or push to `main`; changes reach `main` only through a reviewed PR. Hooks enforce this.
2. Never merge, approve, or close PRs, and never create releases. Those are human decisions.
3. Never read or write `.env*`, keys, `~/.ssh`, `~/.aws`, or real Jarvis user data (`~/.local/share/jarvis`, `%LOCALAPPDATA%\jarvis`). Use synthetic fixtures.
4. When a requirement is ambiguous or missing from the FRS, add an OQ to `docs/open-questions.md` and **stop**. Never assume an answer.
5. Never touch files outside the current task's scope. Refactor OR change behaviour in a commit, never both.
6. Every text file I/O and `subprocess.run(text=True)` passes `encoding="utf-8"`. No `shell=True`.
7. Every tool call in the product goes through the policy gate and the consent check (FRS §5.10–5.11). No side doors, ever.
8. The UI must match `docs/design/jarvis-ui-mockup.html` exactly. The design is frozen (FRS §8.1); changing a token, component or layout needs the owner's sign-off.
9. Update docs in the same change as the code: FRS when behaviour changes, an ADR for hard-to-reverse decisions, `docs/architecture.md` when components change.
10. Never weaken, skip, or delete a test to make it pass.
11. Commits use Conventional Commits and end with the `Co-Authored-By:` trailer for the AI agent used (docs/ai/policy.md §Attribution).
12. Keep PRs small: aim for ≤ 400 changed lines excluding docs and lockfile; split larger work.
13. Show evidence (command plus real output) before saying anything is done or fixed.

## Skills — read before doing

| Before… | Use skill |
|---|---|
| starting any feature or bug fix | `feature-development` |
| writing or changing code in `src/jarvis/` | `python-practices` |
| writing or changing a test | `testing` |
| investigating any error or failing test | `debug` |
| an M0 feasibility experiment | `spike` |
| making a hard-to-reverse decision | `adr` |
| hitting an unclear requirement; before any PR | `open-questions` |
| committing or opening a PR | `code-review` (then the human runs `/open-pr`) |

## Docs — load on demand only

| File | Read before working on |
|---|---|
| `docs/FRS.md` (relevant section only) | Any product behaviour |
| `docs/architecture.md` | Anything spanning more than one component |
| `docs/open-questions.md` | Session start: check for blockers |
| `docs/handoff.md` | Session start: continue where the last session stopped |
| `docs/ai/workflow.md` | Choosing a model, planning a large change, context limits |
| `docs/ai/policy.md` | Data handling, MCP servers, dangerous modes, attribution |
| `docs/ai/lessons.md` | Repeating a mistake an earlier session already made |

## Session hygiene

New task → new session (`/clear`). Plan big changes in Plan Mode and write the plan to `docs/plans/` before coding. At the end of a session, update `docs/handoff.md` (DONE / NEXT / OPEN).
