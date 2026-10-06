---
name: code-review
description: Reviews a diff or PR for correctness, security, scope and tests, reporting findings with file:line. Use before committing, before opening a PR, or when asked to review a branch or PR. Read-only — never edits code.
argument-hint: "[base-ref, default main]"
arguments: [base]
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git log *) Bash(git show *) Bash(gh pr diff *) Bash(gh pr view *) Bash(uv run pytest *)
---

# Code review

Adapted from FiftyfiveTech/claude-base-project-template. Diff: `git diff ${base:-main}...HEAD`.
Review as a fresh pair of eyes: judge the diff and its acceptance criteria, not the author's reasoning.

## Order (correctness first, style last)

1. **Correctness** — walk the logic with a concrete input; don't skim names.
2. **Edge cases** — empty/None, Windows vs Linux paths, unicode, timeouts, device unplugged, brain/MCP unavailable.
3. **Security** — untrusted input (transcripts, message text, web/MCP content) reaching a shell, file path, eval, or a tool call without the policy gate; secrets in code/logs; consent checks bypassed (FRS §5.10–5.11).
4. **Scope** — unrelated changes, drive-by refactors, behaviour change hidden in a refactor.
5. **Tests** — would they fail without the change? Any skipped/weakened tests?
6. **Simplicity** — YAGNI, rule of three before abstracting, delete rather than comment out. Never simplify away validation, error handling or security controls.
7. **Style/naming** — last, and at most 5 nits (tally the rest).

## Jarvis-specific checks

- Every `open()`/`read_text()`/`write_text()`/`subprocess.run(text=True)` passes `encoding="utf-8"`.
- No `shell=True`; no command strings built from user/transcript text.
- Cross-platform branches import platform modules inside the branch.
- Spoken output goes through the response contract sanitiser (FR-IO-02).
- Docs/FRS/ADR updated in the same change when behaviour or decisions changed.

## Output

One line per finding — no citation, no finding:

```
🔴|🟡|🟣  path/file.py:LINE — problem — suggested fix
```

🔴 important (correctness, security, data loss) · 🟡 nit · 🟣 pre-existing. Skip generated files and `uv.lock`. If nothing is wrong, say "No issues found." No praise padding.

## Verify (mandatory)

Run `uv run pytest -q` on the branch and include the summary line. State which findings you confirmed by reading code vs suspected.
