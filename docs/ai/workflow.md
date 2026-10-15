# AI workflow — how we work with agents on Jarvis

Practices from the FiftyFive AI Academy, applied to this repo.

## The loop

**Explore → Plan → Implement → Verify → Commit**, one task per session (skill `feature-development`).

1. **Spec first.** Behaviour comes from `docs/FRS.md`. If it's missing or ambiguous, add an OQ and stop.
2. **Plan big changes.** Use Plan Mode; write the plan to `docs/plans/YYYY-MM-DD-<topic>.md` (5–10 tasks, each ≤ half a day, each with a verify command). Implement it in a **fresh session**.
3. **Thin slices.** Failing test → smallest code → run → commit.
4. **Evidence.** "Done" means the command and its real output.
5. **Review.** The `code-review` skill on the diff, then a human review on the PR.

## Model per task

| Task | Model | Effort |
|---|---|---|
| Routine code, tests, docs, mechanical refactors | Sonnet (default) | normal |
| Architecture, ADRs, policy/consent logic, I/O contract, deep debugging, complex review | Opus | high |
| Trivial lookups, renames | Haiku | low |
| Stuck after 2 attempts, or before > 50 lines of non-trivial code in a risky area | Ask an advisor (Opus) for a second opinion | — |

Never default to the heaviest model. Escalate when the output is shallow or the agent is looping. Check model IDs in the docs before hard-coding them; they change with releases.

## Context and tokens

- New task → `/clear`. Same task with a full context → `/compact`, after moving durable facts into docs.
- Never "resume" a stale chat to start a new task. Hand off through `docs/handoff.md` (DONE / NEXT / OPEN).
- Reference files; don't paste them. Read only the files the task needs. Ask for diffs, not whole files.
- Delegate wide searches to a scoped subagent ("find every caller of X under src/jarvis/policy").
- Commands are quiet by default (`pytest -q`, `ruff --quiet`). Hooks trim failure output to the last 30 lines.

**Session budgets** (check with `/context`):

| Session | Target | Start fresh above |
|---|---|---|
| Bug fix | < 8k | 15k |
| Feature slice | < 15k | 25k |
| Architecture review | < 20k | 35k |
| Multi-file refactor | < 25k | 45k |

## Correct twice, then start clean

Interrupt → ask for a revert → new session with the lesson in the prompt. If the same correction happens three times, it belongs in a hook or a rule. Record it in `docs/ai/lessons.md`.

## Prompts

Context · Task · Constraints · "Done when". One objective per prompt. For bugs: symptom + file + expected vs actual. For refactors: name the smell, say "behaviour must not change", and say how to verify.

## Orchestrated work (milestones)

A milestone runs under one **orchestrator** session (Opus). It owns the plan in `docs/plans/`, `docs/handoff.md` and the order of work, and it never writes product code. For each plan task it dispatches fresh subagents: the **local model loop** (`scripts/local_model.py implement`) drafts the files and fixes them against ruff, mypy and pytest; a **finisher** (Sonnet) completes and commits; a **task reviewer** (Sonnet, Opus for safety-critical code) gates it. Small calls are recorded as rulings for the owner to review later; ambiguous requirements still become OQs. Each task is one small PR stacked on the previous one; the owner merges the stack in order. Full description, with the token and quality levers: [`dev-pipeline.md`](dev-pipeline.md).
