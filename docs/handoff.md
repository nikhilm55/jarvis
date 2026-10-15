# Session hand-off

Rolling note so a fresh session (human or agent) picks up instantly. Overwrite it at the end of every working session; history lives in git.

**Updated:** 2026-10-15 (M1 merged; dev pipeline documented; track W open)

DONE:
- M0 closed; FRS v0.3; frozen UI design; AI-assisted dev setup (ADRs 0001–0011).
- **M1 built** — `docs/plans/2026-10-07-m1-voice-loop.md`, tasks 1–13: mic → Silero VAD → openWakeWord ONNX (lazy, only while speech) → whisper-server → first-word gate → certain-only fast path or a warm, isolated headless Claude Code brain that reaches the PC only through jarvisd's MCP server → deny-by-default, fail-closed policy gate → desktop worker → Kokoro TTS → HUD (ADR-0011) → activity log.
- Every task had a task review (and fix rounds); then a whole-branch review and one final fix wave (SIGHUP/PDEATHSIG for whisper-server, brain stderr log, ToolError logging, settings bounds, reply-window sentinel, private log files).
- **Acceptance Part A:** 17/17 scripted runs on real components; idle CPU ≈ 2.7% of one core (budget 3%) — `docs/milestones/M1-acceptance.md`.
- All M1 PRs merged into `main` (#15 → #114, squash, in order).
- Dev pipeline documented: `docs/ai/dev-pipeline.md`; local-model tool `scripts/local_model.py` (endpoint from `LOCAL_LLM_URL`).

NEXT:
- **Owner:** first live-mic run done (results and findings B1–B5 at the end of `docs/milestones/M1-acceptance.md`). Still untried live: checklist 1–5, "close it", "Jarvis, stop" while thinking, self-trigger.
- **Track W:** custom single-word "Jarvis" wake model (brief in the orchestrator's SDD workspace; stops for owner approval before > 2 GB of downloads; licences decide shippability, OQ-004). Re-run the wake-related acceptance cases with it.
- **Plan M2** (FRS §11 "Hands"): consent layer, confirmations (Safe mode T1 / T2+), more desktop tools, Windows backend. Fold in the M2 backlog below.

M2 BACKLOG (from M1 reviews; details in the PR descriptions):
- Latency: reply speech p50 ≈ 2.2 s after end of speech (Kokoro ≈ 600 ms to first audio vs 400 ms; reply queued behind the thinking earcon); opening an app ≈ 600 ms (waits for the window). Ideas: speak the acknowledgement before the window appears, phrase cache, quantised/smaller voice, don't queue the reply behind the earcon.
- Barge-in while speaking ("Jarvis, stop" during TTS; M1 is deaf while speaking).
- Re-warm the brain in the background after a cancelled turn (cancel kills the warm session).
- Consolidate: one redactor (value + key), one child-env allowlist, a shared loopback-server base for MCP/HUD; one `gated_dispatch` for all desktop callers.
- Audit records carry `turn_id`; fill the activity log's `policy_decisions`.
- Guard the wake detector for classifiers whose window doesn't fit the primed buffer (n_features ≥ 41) — needed before track W lands a different model.
- Inject clocks in timing-sensitive orchestrator tests (CI flake risk).
- From the live run (B1–B5): a "your name" setting so the brain stops using the account's full name; end silently on an empty transcript after a wake; a decline isn't an error in the HUD; idle CPU 3.7 % with a real mic; `tiny.en` vs `base.en` accuracy.
- Owner's phrases as M2 acceptance cases: "open the terminal and check what I've been working on", "help me set up my project" (needs `run_shell` and files).

OPEN:
- OQ-008 (new): may Jarvis's brain touch the user's Claude Code state files (Claude Code writes `~/.claude*` even when isolated)?
- OQ-004 licences now also cover espeak-ng (via Kokoro) and the stock wake model (dev-only).
- OQ-001…006 unchanged; none blocks M2 planning.
- Process: implementation tasks run "plan → local model implements (Claude-free loop) → Sonnet finishes → review"; see `docs/ai/dev-pipeline.md`.
- Dependabot PRs #115–#121 are open (ruff, onnxruntime, pydantic, platformdirs, setup-uv, CodeQL); check each before merging, onnxruntime first.
