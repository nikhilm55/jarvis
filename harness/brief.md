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

## Done when

- [ ] Every requirement has a test that fails without the change and passes with it.
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q` pass (real output in the report).
- [ ] Task-specific checks: …
- [ ] One PR, ≤ 400 reviewable lines, CI green on every required job.

## Report

Answer with [`harness/report.md`](report.md).
