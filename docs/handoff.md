# Session hand-off

Rolling note so a fresh session (human or agent) picks up instantly. Overwrite it at the end of every working session; history lives in git.

**Updated:** 2026-10-15 (M1 merged; harness, Windows CI and the user-name setting merged; track W open)

DONE:
- M0 closed; FRS v0.3; frozen UI design; AI-assisted dev setup (ADRs 0001–0011).
- **M1 built** — `docs/plans/2026-10-07-m1-voice-loop.md`, tasks 1–13: mic → Silero VAD → openWakeWord ONNX (lazy, only while speech) → whisper-server → first-word gate → certain-only fast path or a warm, isolated headless Claude Code brain that reaches the PC only through jarvisd's MCP server → deny-by-default, fail-closed policy gate → desktop worker → Kokoro TTS → HUD (ADR-0011) → activity log.
- Every task had a task review (and fix rounds); then a whole-branch review and one final fix wave (SIGHUP/PDEATHSIG for whisper-server, brain stderr log, ToolError logging, settings bounds, reply-window sentinel, private log files).
- **Acceptance Part A:** 17/17 scripted runs on real components; idle CPU ≈ 2.7% of one core (budget 3%) — `docs/milestones/M1-acceptance.md`.
- All M1 PRs merged into `main` (#15 → #114, squash, in order).
- Dev pipeline documented: `docs/ai/dev-pipeline.md`; local-model tool `scripts/local_model.py` (endpoint from `LOCAL_LLM_URL`).
- **Agent harness** (`harness/`, #125 → #141): brief/report/review templates, a delegation hook, and the local-model loop's sensors (plan against the brief's requirements, tests drafted first then AST-locked, pytest judged by its summary line, scope check, tamper rule, stall stop, fresh-context review). Five adversarial Opus review rounds; limits in `harness/README.md`.
- **Windows CI green** (#123, #138): Linux-only tests skip off Linux with a stated consequence; the brain env allowlist gains 13 Windows OS variables; a timing flake fixed.
- **User name** (#124, #127, #126, #128): `[user] name` set with `jarvis setup --name`; the brain never sees the OS account name (live-run finding B1).

NEXT:
- **Owner:** first live-mic run done (results and findings B1–B5 at the end of `docs/milestones/M1-acceptance.md`). Still untried live: checklist 1–5, "close it", "Jarvis, stop" while thinking, self-trigger.
- **Track W:** custom single-word "Jarvis" wake model (brief in the orchestrator's SDD workspace; stops for owner approval before > 2 GB of downloads; licences decide shippability, OQ-004). Re-run the wake-related acceptance cases with it.
- **M2 "Hands"** is planned: `docs/plans/2026-10-16-m2-hands.md` (14 tasks, Linux X11 only per D15/D17, rulings R80–R91). Waves: 1 and 13 → {2, 3, 5, 6} → {4, 7, 9, 11} → {8, 10, 12} → 14.

M2 BACKLOG (from M1 reviews; details in the PR descriptions):
- Latency: reply speech p50 ≈ 2.2 s after end of speech (Kokoro ≈ 600 ms to first audio vs 400 ms; reply queued behind the thinking earcon); opening an app ≈ 600 ms (waits for the window). Ideas: speak the acknowledgement before the window appears, phrase cache, quantised/smaller voice, don't queue the reply behind the earcon.
- Barge-in while speaking ("Jarvis, stop" during TTS; M1 is deaf while speaking).
- Re-warm the brain in the background after a cancelled turn (cancel kills the warm session).
- Consolidate: one redactor (value + key), one child-env allowlist, a shared loopback-server base for MCP/HUD; one `gated_dispatch` for all desktop callers.
- Audit records carry `turn_id`; fill the activity log's `policy_decisions`.
- Guard the wake detector for classifiers whose window doesn't fit the primed buffer (n_features ≥ 41) — needed before track W lands a different model.
- Inject clocks in timing-sensitive orchestrator tests (CI flake risk).
- Windows: kill the brain's whole process tree (taskkill /T or a Job Object); a second possible flake, `tests/test_desktop_client.py:211`; optionally start the turn clock after the brain's init.
- Harness follow-ups: skip allowance from the skips round 0 actually reports (not from markers); `deselected` counts as not clean; read `tox.ini` addopts.
- Dependabot PRs #115–#121: check each (onnxruntime first) before merging.
- From the live run (B2–B5; B1 done): end silently on an empty transcript after a wake; a decline isn't an error in the HUD; idle CPU 3.7 % with a real mic; `tiny.en` vs `base.en` accuracy.
- Windows: the brain's env allowlist adds 13 OS variables on win32 (SYSTEMROOT, WINDIR, COMSPEC, PATHEXT, USERPROFILE, USERNAME, HOMEDRIVE, HOMEPATH, APPDATA, LOCALAPPDATA, PROGRAMDATA, TEMP, TMP); no secrets; extends R45 (PR #123).
- Windows: kill() on a `.cmd`-launched brain leaves the real process running: use a Job Object; CI should fail on unclosed-transport warnings; CI runs pytest with a doubled -q, so no summary or skip list is printed (needs a .github change).
- Owner's phrases as M2 acceptance cases: "open the terminal and check what I've been working on", "help me set up my project" (needs `run_shell` and files).

OPEN:
- OQ-008 (new): may Jarvis's brain touch the user's Claude Code state files (Claude Code writes `~/.claude*` even when isolated)?
- OQ-004 licences now also cover espeak-ng (via Kokoro) and the stock wake model (dev-only).
- OQ-001…006 unchanged; none blocks M2 planning.
- Process: implementation tasks run "plan → local model implements (Claude-free loop) → Sonnet finishes → review"; see `docs/ai/dev-pipeline.md`.
