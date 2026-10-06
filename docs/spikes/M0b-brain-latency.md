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

Run on 2026-10-06 with Claude Code 2.1.291, model aliases `sonnet`, `haiku` and `opus`, on the dev machine in the plan. Sessions were isolated with `--setting-sources project` in an empty temp dir and `--strict-mcp-config`; the only hook was the policy stub. There were 20 measured turns per run (14 answer-only, 6 one-tool), plus a warm-up and a deny turn. 0 turns failed. Raw data: `M0b-brain-latency.data.csv`. Harness: `spikes/M0b-brain-latency/`.

| Model | Mode | Turn kind | n | first token p50 | total p50 | total p95 | max |
|---|---|---|---|---|---|---|---|
| sonnet | cold | answer | 14 | 2.19 s | 2.26 s | 4.74 s | 5.05 s |
| sonnet | cold | tool | 6 | 3.69 s | 3.71 s | 12.33 s | 12.33 s |
| **sonnet** | **warm** | **answer** | 14 | 1.38 s | **1.41 s** | **1.50 s** | 2.95 s |
| **sonnet** | **warm** | **tool** | 6 | 3.08 s | **3.10 s** | **3.21 s** | 3.21 s |
| haiku | warm | answer | 14 | 1.15 s | 1.18 s | 2.56 s | 2.71 s |
| haiku | warm | tool | 6 | 3.48 s | 3.50 s | 10.98 s | 10.98 s |
| opus | warm | answer | 14 | 1.07 s | 1.59 s | 1.95 s | 2.45 s |
| opus | warm | tool | 6 | 2.98 s | 3.00 s | 3.24 s | 3.24 s |

**Policy hook** (command hook → loopback HTTP stub → allow/deny):

| Measured | n | p50 | p95 | max |
|---|---|---|---|---|
| Inside the hook script (HTTP round trip) | 20 | 15.0 ms | 16.5 ms | 21.4 ms |
| Whole hook process (spawn + Python start + HTTP) | 30 | 82.3 ms | 110.6 ms | 164.1 ms |

**Deny honoured:** on all three models the denied `echo DENYME` never ran, and the model explained the block in plain words.

**Against the pass bar:**

| Bar | Result | |
|---|---|---|
| Warm p50 ≤ 4 s | 1.41 s (answer) / 3.10 s (tool) | ✅ |
| Warm p95 ≤ 7 s | 1.50 s / 3.21 s | ✅ |
| Hook p95 ≤ 150 ms | 110.6 ms whole process | ✅ (max 164 ms) |
| Deny honoured | 3 / 3 models | ✅ |

**Hypothesis corrections:**
- Cold was faster than predicted: p50 2.3 s, not > 6 s.
- Cold's tail is much worse, though: p95 4.7 s and 12.3 s. Warm also saves about 0.6–0.9 s per turn.

**Limitations:**
- Small n for tool turns (6 per run): treat the p95 values as indicative only.
- One machine, one time of day, one network.
- Single trivial tool calls; no MCP servers loaded and no long-context growth across a warm session. Re-measure in M1 with real tools.

## Decision

**GO: Claude Code as the default brain, running a warm stream-json session** (confirms ADR-0003, FR-BRN-02/03).

**Consequences:**
- Keep one warm session per conversation, and start it (with a warm-up turn) when jarvisd starts, so that turn's latency is paid up front.
- The brain's floor is about 1.2–1.4 s even for trivial answers. So the local **fast path** (FR-NLU-01, ≤ 300 ms) stays necessary for common commands, and the 1.2 s spoken acknowledgement (FR-TALK-02) is needed for tool turns.
- A policy gate through a PreToolUse hook is viable, but process spawn costs about 70 ms of the hook's 82 ms. In M1, evaluate Claude Code's HTTP hook type pointed at jarvisd's loopback endpoint (no process spawn); fall back to a command hook.
- Model choice: Opus was no slower than Sonnet here, and Haiku had no latency advantage on tool turns. Choose the default model on answer quality, not speed. Model routing (FR-BRN-08) stays C.
- No FRS budget changes: §7.1 holds for the brain path.
