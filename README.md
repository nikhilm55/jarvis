# Jarvis

Voice control for your whole PC. Say **"Jarvis, …"** and it gets done. If it can't, it tells you why and what to do.

> **Status: M1 built (the voice loop, Linux X11).** Jarvis hears "Jarvis, …", opens and closes apps, tells the time, sets the volume, and hands anything else to a locked-down Claude Code "brain" that talks back. Next: **M2 "Hands"**: shell, files, typing, reading the screen, confirmations, Windows. See the [roadmap](#roadmap).

## What works today

| Say | What happens |
|---|---|
| "Jarvis, open Calculator" / "close Calculator" | Opens or closes the app (fast path, no AI call) |
| "Jarvis, what time is it?" | Speaks the time |
| "Jarvis, volume up" / "set volume to 30 percent" | Changes the system volume |
| "Jarvis." … *(chime)* … "open Calculator" | Wake first, command second |
| "Jarvis, please open the terminal for me" | The Claude Code brain works it out, acts through Jarvis's own tools, and answers |
| "I told Jarvis to open Calculator" | Nothing: "Jarvis" must be the first word after a pause |

How it works: mic → voice activity detection (Silero) → wake word (openWakeWord) → speech to text (whisper.cpp) → either a **fast path** for certain commands or the **brain** (a warm, isolated, headless Claude Code session that can reach the PC only through Jarvis's MCP server) → a deny-by-default **policy gate** → the desktop worker → speech (Kokoro) → an on-screen HUD pill. Every turn is written to an activity log. Details: [`docs/architecture.md`](docs/architecture.md).

Measured in M1 acceptance ([`docs/milestones/M1-acceptance.md`](docs/milestones/M1-acceptance.md)): 17/17 scripted voice commands pass on the real components; idle CPU ≈ 2.7 % of one core with a file source (3.7 % with a live mic); a sound about 1.3 s after you stop speaking, the spoken answer about 2.2 s after.

## Try it (Linux, GNOME on X11)

You need:

- [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11
- system packages: `sudo apt install libportaudio2 python3-gi gir1.2-webkit2-4.1` (PipeWire's `wpctl` ships with Ubuntu)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) built with its `whisper-server` binary
- [Claude Code](https://docs.claude.com/en/docs/claude-code), installed and logged in, for the brain (optional: `--no-brain` runs the fast path only)

```
uv sync
uv run jarvis models fetch                       # VAD, wake, speech-to-text and voice models
export JARVIS_WHISPER_SERVER=/path/to/whisper.cpp/build/bin/whisper-server
uv run jarvis setup --name "<your name>"         # what Jarvis calls you (optional; no name is used until you set one)
uv run jarvis run                                # add --no-brain or --no-hud if you like
```

Then say "Jarvis, what time is it?". `uv run jarvis --help` lists the other commands (`say`, `listen`, `models`, `setup`). The wake model is still the stock dev `hey_jarvis` model; a custom "Jarvis" model is in progress.

## Docs

| | |
|---|---|
| Spec | [`docs/FRS.md`](docs/FRS.md) |
| Architecture | [`docs/architecture.md`](docs/architecture.md) · decisions in [`docs/adr/`](docs/adr/0001-record-architecture-decisions.md) |
| UI design (approved, frozen) | [`docs/design/jarvis-ui-mockup.html`](docs/design/jarvis-ui-mockup.html) |
| Plans and acceptance | [`docs/plans/`](docs/plans/) · [`docs/milestones/`](docs/milestones/) |
| Where we are | [`docs/handoff.md`](docs/handoff.md) · [`docs/open-questions.md`](docs/open-questions.md) |
| How it's built | [`docs/ai/dev-pipeline.md`](docs/ai/dev-pipeline.md) · the agent harness [`harness/`](harness/README.md) |
| Working with AI agents | [`AGENTS.md`](AGENTS.md) · [`docs/ai/onboarding.md`](docs/ai/onboarding.md) · [`docs/ai/workflow.md`](docs/ai/workflow.md) · [`docs/ai/policy.md`](docs/ai/policy.md) |

## Develop

```
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pre-commit run --all-files && uv run mypy && uv run pytest -q
```

Python 3.11+, uv, ruff, `mypy --strict`, pytest. `main` is protected: every change lands through a small PR (≤ 400 reviewable lines) with CI on Ubuntu and Windows, CodeQL and dependency review. Full setup, including the Claude Code guardrails, is in [`docs/ai/onboarding.md`](docs/ai/onboarding.md); contribution rules in [`CONTRIBUTING.md`](CONTRIBUTING.md).

### How we build it

Jarvis is built by AI agents under one human owner, in a pipeline designed to spend as few Claude tokens as possible without lowering the bar:

- **Claude Opus orchestrates:** it writes the plan and a precise brief per task, and never writes product code.
- **A local model writes the code:** Qwen 27B on the owner's GPU drafts every file and fixes it against ruff, mypy and pytest in a loop with no Claude in it (`scripts/local_model.py`).
- **Claude Sonnet finishes and reviews:** it sees only the diff and the remaining errors. Opus reviews safety-critical code and each milestone as a whole.
- **The owner decides:** they run the live tests and merge.
- **Everything runs inside one [agent harness](harness/README.md):**
  - **Guides before the model acts:** a precise brief with "done" agreed up front, a plan that maps each requirement to a test, and house rules.
  - **Sensors after it acts:** tests written first and then locked so they can't be weakened, lint, strict types, a scope check, a fresh-context review, and CI.
  - **Ratchet:** every mistake a check could have caught becomes a new check.
  - **Enforced:** a hook rejects any subagent brief that skips it.

M1 went in as 100 small, reviewed PRs, with the local model writing most of the lines. The roles, the flow, the token levers and the quality gates are in [`docs/ai/dev-pipeline.md`](docs/ai/dev-pipeline.md).

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 Spikes | Wake word, brain latency, X11/Wayland control | Done |
| M1 Voice loop | Mic → wake → STT → brain/fast path → TTS, HUD, activity log (Linux X11) | **Built**; owner's live run done; custom wake model in progress |
| M2 Hands | Shell, files, typing, screen reading, confirmations and consent, Windows backend | Next |
| M3 Integrations | Teams/Outlook, Google, Slack, browser, memory | Planned |
| M4 Setup and polish | Setup wizard, installers, main window, routines | Planned |
| M5 Beta | Acceptance suite ≥ 85 %, offline installer | Planned |
