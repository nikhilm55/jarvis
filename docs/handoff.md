# Session hand-off

Rolling note so a fresh session (human or agent) picks up instantly. Overwrite it at the end of every working session; history lives in git.

**Updated:** 2026-10-07 (M1 planned; orchestrated work starts)

DONE:
- FRS v0.3 (D15–D17: Linux first, sign-ins via setup only, v1 = GNOME on X11). UI design frozen (`docs/design/jarvis-ui-mockup.html`).
- AI-assisted dev setup (audit 4.80/5): AGENTS.md/CLAUDE.md, hooks, sandbox, skills, CI with a PR-size gate, ADRs 0001–0010.
- **M0 closed** (cards in `docs/spikes/`): brain GO, desktop on X11 GO (ADR-0008), wake-word architecture GO with a custom model needed, Teams moved to M3, Wayland deferred (ADR-0009).
- **M1 planned:** `docs/plans/2026-10-07-m1-voice-loop.md` (13 tasks + track W), stack in ADR-0010.

NEXT:
- The orchestrator session issues worker prompts in plan order. Wave 1: task 1 (foundation). Then tasks 2–6 and track W in parallel.
- Workers: do only the task in your prompt; end with a REPORT block (`docs/ai/workflow.md` §Orchestrated work).

OPEN:
- OQ-004 now also covers model/library licences found in M1 (stock wake models, espeak-ng). Must be settled before distribution, not before M1.
- OQ-001 (Teams tenant) belongs to M3. OQ-002, 003, 005, 006 don't block M1.
