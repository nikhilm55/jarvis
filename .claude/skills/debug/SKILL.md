---
name: debug
description: Fixes a failing test, crash or "it broke" report with the reproduce → isolate → fix → regression-test loop. Use for any bug, error, traceback or unexpected behaviour in Jarvis, before proposing a fix.
argument-hint: "<symptom: what happened vs what was expected>"
arguments: [symptom]
allowed-tools: Read Grep Glob Edit Write Bash(uv run *) Bash(git diff *) Bash(git log *) Bash(git stash *)
---

# Debug

Symptom: **$symptom**

## Loop — do not skip a step

1. **Reproduce.** Write the smallest command or failing test that shows the bug. If you cannot reproduce it, ask for exact steps, OS (Windows/Linux, X11/Wayland) and logs. Never patch blind.
2. **Isolate.** Read the traceback and logs (`jarvis` logs are JSON lines; see FRS FR-LOG-05). State the single most likely cause and the evidence for it *before* changing code.
3. **Fix.** Smallest change that fixes the cause. No unrelated refactors.
4. **Regression test.** Add a test that fails before the fix and passes after (skill `testing`).

## The 90%→100% loop for error lists

Collect ALL errors (ruff, mypy, pytest) into one list → fix them together → re-run → if anything new appeared, revert that change completely rather than stacking fixes. Stuck after 2 attempts → stop, summarise what was tried, and escalate (fresh session or advisor/Opus) — see docs/ai/workflow.md.

## Usual suspects in this codebase

- Missing `encoding="utf-8"` (Windows cp1252) · PATH differences under desktop launchers · `shell=True` quoting · platform module imported outside its branch · audio device sample-rate mismatch · Wayland blocking input/overlay · subprocess left running (track PIDs).

## Anti-patterns

- ❌ Changing several files "to be safe" — hides the real cause.
- ❌ Deleting or loosening the failing assertion.
- ❌ Catching and swallowing the exception.

## Verify (mandatory)

`uv run pytest -q` passes, the new regression test is in the diff, and you paste both the before (failing) and after (passing) output.
