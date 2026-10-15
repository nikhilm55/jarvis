---
name: delegate
description: Use before handing any task to a subagent or the local model (implementer, finisher, reviewer, researcher) — writes the brief from the harness template and sets up the review
allowed-tools: Read Grep Glob Write Bash(uv run python scripts/local_model.py *) Bash(git diff *) Bash(gh pr checks *)
---

# Delegate a task through the harness

1. Read `harness/README.md` once per session.
2. Write the brief from `harness/brief.md`. Keep all five required headings: Goal, Context, Constraints, Done when, Report. The delegation hook rejects a prompt without them.
   - Fill **Requirements** with numbered, testable items, and the **Manifest** with the files to write, read and test.
   - Put every limit as a number: CI rounds, live runs, paid calls.
3. Choose the worker (`docs/ai/dev-pipeline.md` §Roles):
   - **Code from a precise brief:** `uv run python scripts/local_model.py implement --spec <brief> --write … --read … --test …`, then a Sonnet finisher with the diff, `summary.json` and the remaining errors.
   - **Debugging, judgement or cross-cutting work:** a Claude implementer.
   - **Review:** a different Claude instance with `harness/review.md` and the review package (brief + diff + verify output + CI status). Use Opus for the policy gate, brain isolation and consent.
4. When the report arrives, check it against `harness/report.md`: is the requirement → test map true, is the evidence real, and does the scope match the manifest?
5. **Ratchet:** if review found something a check could have caught, add that guide or sensor in the fix round.

## Verify

Before dispatching: the brief has all five required headings, every requirement is numbered and testable, and every limit is a number. After the report: you opened at least one mapped test and the PR's CI status yourself.
