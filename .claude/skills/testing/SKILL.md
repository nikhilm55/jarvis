---
name: testing
description: Writes or reviews pytest tests for Jarvis — what to cover, structure, naming, fakes for OS/audio/LLM boundaries, flake prevention. Use when writing any test, fixing a bug (reproduce with a failing test first), or reviewing test changes.
argument-hint: "<module or behaviour under test>"
arguments: [target]
allowed-tools: Read Grep Glob Edit Write Bash(uv run pytest *) Bash(uv run ruff *) Bash(uv run mypy *)
---

# Testing

Adapted from FiftyfiveTech/claude-base-project-template. Target: **$target**

## Rules

1. **Test first.** Write the test, run it, confirm it fails *for the right reason*, then implement. For bugs, the failing test reproduces the bug before any fix.
2. **One behaviour per test**, Arrange / Act / Assert, named `test_should_<behaviour>_when_<condition>`. If the name needs "and", split it.
3. **Cover:** happy path · edges (empty, None, zero, max, duplicates, very long input, unicode/Hindi text, Windows paths with spaces/apostrophes) · error paths asserting the *specific* exception or error code (Appendix B of the FRS).
4. **Mock only boundaries:** microphone, speaker, network (Groq/Anthropic/MCP), OS automation, clock, filesystem outside `tmp_path`. Prefer a cheap fake (in-memory, `tmp_path`) over a mock. Never mock the code under test.
5. **Inject runners** for OS calls (`subprocess`, UI automation, PipeWire, WASAPI) so Windows code is testable on Linux — the beyondMeetings pattern.
6. **No flakes:** no `sleep` (wait on a condition), inject the clock, seed randomness, no shared mutable state, tests pass in any order.
7. **Synthetic data only.** Fixtures live in `tests/fixtures/`; never real recordings, transcripts, contacts or messages (docs/ai/policy.md §Data).
8. **Never** weaken a test to go green: no `skip`/`xfail` without an OQ id in the reason, no deleted assertions, no lowered thresholds.
9. Coverage is a smell detector, not a goal — concentrate on the policy gate, consent layer, I/O contract validation and wake-word gating.

## Commands

| Need | Command |
|---|---|
| Whole suite | `uv run pytest -q` |
| One file | `uv run pytest tests/test_x.py -q` |
| One test | `uv run pytest tests/test_x.py::test_should_y_when_z -q` |
| Coverage | `uv run pytest --cov=jarvis --cov-report=term-missing -q` |

## Verify (mandatory)

1. Revert the fix → the new test must fail. Restore → it passes.
2. Run the whole suite: `uv run pytest -q`. Paste the summary line.
