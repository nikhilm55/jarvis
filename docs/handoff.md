# Session hand-off

Rolling note so a fresh session (human or agent) picks up instantly. Overwrite it at the end of every working session; history lives in git.

**Updated:** 2026-10-07 (M0 closed)

DONE:
- FRS v0.3, including the consent layer (decisions D15–D17: Linux first, sign-ins via setup only, v1 = GNOME on X11). UI design frozen (`docs/design/jarvis-ui-mockup.html`).
- AI-assisted dev setup (audit 4.80/5): AGENTS.md/CLAUDE.md, hooks, sandbox (working on the dev machine), skills, CI with a PR-size gate, ADRs 0001–0009.
- **M0 closed.** Cards in `docs/spikes/`:
  - M0b brain: GO. Warm Claude Code session, 1.4 s answers / 3.1 s tool turns; policy hook 82 ms.
  - M0c desktop on X11: GO. Automation runs in a worker process using EWMH (ADR-0008).
  - M0a wake word: architecture GO (0 false accepts in 60 min, 0 mid-sentence); recall at the bar. The stock "hey_jarvis" model must be replaced by a custom "Jarvis" model.
  - M0d Teams: moved to M3 (setup-driven sign-in). Wayland: deferred (ADR-0009).

NEXT:
- Plan M1, the voice loop on Linux X11 (FRS §11): mic → wake (custom model + first-word gate) → STT → warm Claude Code brain → I/O contract → TTS, plus basic HUD, fast path and activity log. Write `docs/plans/<date>-m1-voice-loop.md` first.
- Optional, any time: the owner's 15-min real-voice set (`spikes/M0a-wake-word/record.py`) to validate wake-word recall.

OPEN:
- OQ-001 (Teams tenant consent) now belongs to M3. OQ-002…006 in `docs/open-questions.md`; none blocks M1.
