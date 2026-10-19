# Brief: <one-line task title>

<!-- Every delegated task starts from this template. The five required sections (Goal, Context,
Constraints, Done when, Report) are checked by .claude/hooks/guard_delegation.py. Delete the
comments; keep the headings. Be concrete: exact names, paths, signatures, numbers. -->

## Goal

What changes for the user or the codebase when this is done, in 1–3 sentences. Why it matters.

## Context

- Spec: the FRS sections / ADRs / rulings this implements (by number).
- Read first: the files the worker must read (only those).
- Interfaces to honour: exact signatures, data shapes and error types this task must produce or call.
- Facts the worker can't find alone: external API behaviour, measured numbers, past decisions.

## Local model

Mode: `loop` | `finisher` | `review` | `exempt: <reason>`.

- `loop`: the delegator runs `uv run python scripts/local_model.py implement --spec <this brief> --write <tests first, then modules> --read <context> --test <tests> --log-dir <workspace>/runs/<task>` before any Claude agent writes code.
- `finisher`: the loop has run; give its log dir and `summary.json` status. The worker finishes from the diff and the remaining errors.
- `review`: no code is written.
- `exempt: <reason>`: allowed reasons are the loop being unreachable, debugging or diagnosis, a small edit to already-reviewed code, and docs. Name the files the exemption covers.

## Manifest

- Write: `path/one.py`, `tests/test_one.py`
- Read: `path/two.py`
- Test: `tests/test_one.py`

## Requirements

Numbered, each one testable. The worker maps every number to a named test.

1. …
2. …

## Constraints

- Scope: only the manifest's files change. No new dependencies unless named here.
- House rules: `AGENTS.md` (mypy --strict, ruff, `encoding="utf-8"`, no `shell=True`, tests with `tmp_path`/`monkeypatch`).
- Limits: CI rounds, live runs, paid calls, wall time. Say the number.
- Never: merge or approve PRs, push to `main`, read secrets or real user data, weaken or skip a test to make it pass.
- Out of scope: what not to do, even if tempting.
- Standing rules learned from earlier reviews (keep the ones that apply):
  - A step that reports success checks its postcondition on the result itself, not through a check that can't see what it changed.
  - An editor of a structured file (TOML, JSON, YAML) verifies by parsed-data equality: everything except the edited key is unchanged. A successful parse is not enough.
  - Atomic writes: a unique temp file in the same directory, cleanup on every failure path, keep the file mode, follow symlinks, fsync before replace, and map decode/encode errors to the domain error.
  - Security-relevant allowlists and platform branches get a unit test for each branch, including one proving the old behaviour on the unchanged platform.
  - Platform skips use `sys.platform != "linux"` (or the platform that has the feature), and the reason states what breaks on the skipped platform.
  - Removing a config key: the unknown-key error tells the user what to do instead.
  - Prefer behavioural tests (set the input, check the output) to tests that grep the source.
  - Test the unusual syntactic forms of anything an editor or parser touches: inline tables, quoted keys, multi-line strings, CRLF.

## Done when

- [ ] Every requirement has a test that fails without the change and passes with it.
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q` pass (real output in the report).
- [ ] Task-specific checks: …
- [ ] One PR, ≤ 400 reviewable lines, CI green on every required job.

## Report

Answer with [`harness/report.md`](report.md).
