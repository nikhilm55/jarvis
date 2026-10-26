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

A per-file author table:

| File | Mode (loop / finisher / exempt: reason) | Loop status and log dir | Local model's surviving share |
|---|---|---|---|

Then fix rounds and what each model got wrong. A low share is useful data, not a failure. A missing table, or a file written by Claude with no exemption in the brief, fails review.

## Open questions and follow-ups

New OQs (added to `docs/open-questions.md`), follow-ups for later tasks, and any guide or sensor this task showed is missing (the ratchet).
