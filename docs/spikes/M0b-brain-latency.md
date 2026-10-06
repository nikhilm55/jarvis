# M0b — Can Claude Code be a fast, policy-gated brain?

**Hypothesis:** a warm Claude Code session (stream-json in/out, kept alive between turns) answers a simple tool-using command in p50 ≤ 4 s and p95 ≤ 7 s (FRS §7.1). A cold `claude -p` per turn is too slow (expected > 6 s p50). A PreToolUse hook that asks a local policy endpoint adds ≤ 150 ms p95.
**FRS refs:** FR-BRN-02, FR-BRN-03, FR-SAFE-01, §7.1 latency budget, ADR-0003, ADR-0004.
**Method:**
1. Fixed prompt set (20 turns): 10 "answer only" turns, and 10 turns that need one tool call (a dummy `jarvis.respond` style JSON output, plus one Bash `echo`).
2. Cold: a new `claude -p --output-format stream-json` process per turn. Warm: one long-lived `--input-format stream-json` process fed turn by turn.
3. Measure wall time from sending the turn to (a) the first assistant token and (b) the final result event, from stream-json timestamps.
4. Hook cost: a PreToolUse hook POSTs to a localhost stub policy server (allow/deny). Measure the hook's own runtime and the end-to-end difference with the hook on and off.
5. Same model for all runs; record the model ID and Claude Code version.
**Pass bar:** warm p50 ≤ 4 s and p95 ≤ 7 s to the final result; hook p95 ≤ 150 ms; a deny is honoured, with the tool not executed.
**Time-box:** 4 h.

## Result

_Pending._

## Decision

_Pending._
