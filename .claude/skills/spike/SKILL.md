---
name: spike
description: Runs a time-boxed feasibility spike (M0) — hypothesis, measurement, go/no-go — and records the result in docs/spikes/. Use when a risky assumption must be proven before building, e.g. wake-word accuracy, Claude Code latency, Wayland control, Teams access.
argument-hint: "<spike id, e.g. M0a-wake-word>"
arguments: [spike_id]
allowed-tools: Read Grep Glob Edit Write Bash(uv run *) Bash(git status) Bash(git diff *)
---

# Spike: $spike_id

Spikes answer a question with numbers. Spike code is throwaway: it lives under `spikes/$spike_id/`, is never imported by `src/`, and is deleted or rewritten properly once the decision is made.

## 1. Write the card first — `docs/spikes/$spike_id.md`

```
# $spike_id — <question>
Hypothesis:   <what we expect, with a number>
FRS refs:     <FR ids / risk in FRS §12.1>
Method:       <how it will be measured, on which OS/hardware>
Pass bar:     <go/no-go threshold, e.g. false-accept ≤ 1 per 8 h, p50 ≤ 4 s>
Time-box:     <hours>
```

## 2. Run it

- Smallest code that measures the thing. Log raw numbers to `docs/spikes/$spike_id.data.csv` (synthetic or self-recorded audio only — never other people's voices or messages).
- Record versions (OS, Python, library versions, model names) — results are meaningless without them.
- Hit the time-box → stop and report what is known.

## 3. Decide

Append to the card: **Result** (numbers vs pass bar), **Decision** (go / no-go / pivot), **Consequences**. If the decision changes the design, write an ADR (skill `adr`) and update the FRS section it affects. Unanswered questions → `docs/open-questions.md`.

## Verify (mandatory)

The card has Hypothesis, Method, Pass bar, Result with real numbers, and Decision. `uv run pytest -q` still passes (spike code must not break the suite). Show the card.
