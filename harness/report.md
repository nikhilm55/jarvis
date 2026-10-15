# Report: <task title>

<!-- Every worker ends with this. Evidence over adjectives: commands and their real output. -->

**Status:** DONE | DONE_WITH_CONCERNS | BLOCKED (one line why)
**PR / commits:** link, commit range

## Requirement → test map

| # | Requirement (from the brief) | Test | Passes |
|---|---|---|---|
| 1 | … | `tests/test_x.py::test_should_…` | yes |

## Evidence

```
$ uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
<last lines of the real output>
```

Task-specific checks and their output. CI status of every required job.

## Deviations from the brief

What differs and why. "None" if none.

## Who wrote what

Share of final lines per model (e.g. local model ~85 % of `x.py`, the rest Sonnet), fix rounds, and what each model got wrong. A low share is useful data, not a failure.

## Open questions and follow-ups

New OQs (added to `docs/open-questions.md`), follow-ups for later tasks, and any guide or sensor this task showed is missing (the ratchet).
