---
name: feature-development
description: Builds one feature or fixes one bug end to end — scope, plan, implement in thin slices, verify, commit. Use when starting any coding task in Jarvis, when a task is drifting, or when the same correction has been given twice.
argument-hint: "<one-sentence task>"
arguments: [task]
allowed-tools: Read Grep Glob Edit Write Bash(uv run *) Bash(git status) Bash(git diff *) Bash(git switch *) Bash(git add *) Bash(git commit *)
---

# Feature development

Adapted from FiftyfiveTech/claude-base-project-template. Task: **$task**

## 1. Define done before code

Fill this in and show it before writing anything:

```
Goal:         <one sentence — what the user gets>
FRS refs:     <FR-xxx ids from docs/FRS.md this satisfies>
Done when:    <exact command + expected output, e.g. `uv run pytest tests/test_wake.py -q` → all pass>
Touching:     <files/modules expected to change>
Out of scope: <what this task explicitly does NOT do>
```

If an FRS requirement is ambiguous or missing, add an OQ to `docs/open-questions.md` (skill `open-questions`) and **stop** — never guess.

## 2. Explore, then plan

- Read only the files the task needs. Point at an existing pattern ("follow `X` in `src/jarvis/…`") rather than inventing one.
- For anything bigger than one file: write the plan to `docs/plans/<date>-<topic>.md` (5–10 tasks, each ≤ half a day, each with its own verify command), then implement in a **fresh session**.
- Hard-to-reverse decisions (policy gate, I/O contract, config schema, platform abstraction) → write an ADR first (skill `adr`).

## 3. Implement in thin vertical slices

- Branch first: `git switch -c feat/<topic>` (hooks block commits on `main`).
- Each slice = failing test → smallest code to pass → run it. Never generate ahead of what has been verified.
- Follow `python-practices`. Refactor OR add behaviour in a commit, never both.
- Commit at every green state with a Conventional Commit message and the `Co-Authored-By` trailer (docs/ai/policy.md §Attribution).

## 4. Course-correct twice, then start clean

Interrupt → ask for a revert → fresh session with the lesson in the prompt. Record the lesson in `docs/ai/lessons.md` if it should become a rule.

## 5. Verify (mandatory — evidence, not claims)

Run and paste the real output:

```
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

Then run the `code-review` skill on the diff. Report: the "Done when" command and its actual output, files changed, any OQs opened.
