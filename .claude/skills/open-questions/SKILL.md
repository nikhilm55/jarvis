---
name: open-questions
description: Tracks unresolved decisions in docs/open-questions.md — add a new OQ, audit code for silently assumed answers, or resolve one OQ with a decision. Use when a requirement is ambiguous, at session start to check blockers, and before opening a PR.
argument-hint: "add <title> | audit | resolve OQ-NNN \"<decision>\""
arguments: [action, id, decision]
allowed-tools: Read Grep Glob Edit Bash(git diff *) Bash(git log *)
---

# Open questions

The file `docs/open-questions.md` is the safety net: unresolved decisions are tracked, never guessed. Keep fewer than 10 open.

## add — `$action` = add

Append the next id (`OQ-NNN`, 3 digits) using this shape, then **stop the current task** if it depends on the answer:

```
## OQ-NNN — <title>
**Status:** open
**Owner:** @<github-handle>
**Context:** <where it came up, FRS ref>
**Question:** <one question>
**Impact:** <what is blocked or at risk>
```

## audit — before every PR

Scan the branch diff (`git diff main...HEAD`) and `src/` for answers assumed without a decision: `TODO`/`FIXME`/`HACK`, hard-coded values that the FRS leaves open, stubs, `NotImplementedError`, magic thresholds. For each hit: already tracked → skip; new → add an OQ. Output `X new, Y tracked, Z skipped`.

## resolve — `$action` = resolve `$id` "$decision"

One OQ per run. Set `**Status:** resolved — $decision (@who, YYYY-MM-DD)`. Apply the decision where it belongs (FRS section, ADR if hard to reverse, code). Never resolve an OQ the human has not decided.

## Verify (mandatory)

Show the changed entries. Confirm every open OQ has an Owner and the open count is < 10; if not, say so.
