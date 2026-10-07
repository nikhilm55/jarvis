# Session hand-off

Rolling note so a fresh session (human or agent) picks up instantly. Overwrite it at the end of every working session; history lives in git.

**Updated:** 2026-10-07 (M0 closed)

DONE:
- FRS v0.3 written (`docs/FRS.md`), including the consent layer. UI design approved and frozen (`docs/design/jarvis-ui-mockup.html`).
- AI-assisted development setup: AGENTS.md/CLAUDE.md, hooks, permissions + sandbox, skills, ADRs 0001–0007, AI policy docs, CI.

- M0b brain latency: GO. Warm Sonnet is 1.4 s for answers and 3.1 s for tool turns (p50); the policy hook costs 82 ms p50. See `docs/spikes/M0b-brain-latency.md`.
- M0c part 1 (X11): GO for every core capability, including input (XTest via ctypes, AT-SPI insert and keys). Crashes come from libwnck/PyGObject teardown, not from the operations, so automation runs in a worker process, with EWMH instead of libwnck. See `docs/spikes/M0c-desktop-control.md`.
- M0a wake word (synthetic voices): architecture GO, model PIVOT. Detector + Whisper first-word gate: 0 false accepts in 60 min, 0/200 mid-sentence, 94–95% recall at the bar. Next: a custom 'Jarvis' model and real-voice validation. See `docs/spikes/M0a-wake-word.md`.

NEXT:
- Plan M1, the voice loop on Linux X11 (FRS §11): mic → wake (custom model + first-word gate) → STT → warm Claude Code brain → I/O contract → TTS, plus basic HUD, fast path and activity log. Write `docs/plans/<date>-m1-voice-loop.md` first.
- Optional, any time: the owner's 15-min real-voice set (`spikes/M0a-wake-word/record.py`) to validate wake-word recall.

OPEN:
- OQ-001 (Teams tenant consent) now belongs to M3. OQ-002…006 in `docs/open-questions.md`; none blocks M1.
