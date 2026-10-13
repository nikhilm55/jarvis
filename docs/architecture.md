# Architecture overview

Concise map for humans and agents. Details live in `docs/FRS.md` (§4 overview, §9 stack). Decisions behind it: `docs/adr/`.
**Status:** designed, not built. M0 spikes (FRS §11) validate the risky parts first.

## One turn

```
Mic ─▶ wake word "Jarvis" ─▶ VAD ─▶ STT ─▶ first-word gate ─▶ orchestrator
                                                              │
                     ┌──────────── fast path (local intents) ◀┤
                     ▼                                        ▼
             policy gate + consent ◀──────────────▶ brain (Claude Code / API / local LLM URL)
                     │
                     ▼
        tools: jarvis-desktop MCP · user MCP servers
                     │
                     ▼
     response contract (validated JSON) ─▶ TTS + HUD
```

Principle (ADR-0004): **the model decides, deterministic code executes and presents.** The brain chooses what to do and what to say. jarvisd decides whether it is allowed (policy and consent) and how it is shown and spoken.

## Processes

| Process | Role | Planned module |
|---|---|---|
| `jarvisd` | Audio, wake word, VAD, STT, orchestrator, policy gate, consent, TTS, local API, scheduler | `jarvis/daemon` |
| jarvis-desktop MCP | OS control tools (apps, windows, input, screen, files), served by jarvisd over loopback | `jarvis/tools` |
| Brain | Warm Claude Code headless session, or jarvisd's own agent loop for API/URL brains | `jarvis/brain` |
| User MCP servers | Child processes or remote URLs from the catalog | `jarvis/mcp` |
| UI | HUD overlay, palette, main window (pywebview + local web UI) | `jarvis/ui` |

## Component map (planned packages)

| Package | Responsibility | FRS |
|---|---|---|
| `jarvis.audio` | Mic stream, device selection, AEC (per-OS backends) | §5.2 |
| `jarvis.wake` | Wake word, VAD, first-word gate | §5.1 |
| `jarvis.stt` | Groq / whisper.cpp transcribers | §5.3 |
| `jarvis.brain` | Brain providers, I/O contract, agent loop | §5.5–5.6 |
| `jarvis.policy` | Risk tiers, modes, guardrails, consent grants | §5.10–5.11 |
| `jarvis.tools` | jarvis-desktop MCP tools, per-OS backends | §5.8 |
| `jarvis.tts` | Speech output, earcons, captions | §5.7 |
| `jarvis.ui` | HUD, palette, main window (frozen design) | §5.16, §8 |
| `jarvis.setup` | Doctor checks and wizard (ported from beyondMeetings) | §5.17 |

## Brain session (M1: Claude Code)

`jarvis.brain.ClaudeCodeBrain` keeps one `claude -p` process warm over stream-json and starts it isolated from the user's Claude Code setup: no user/project/local settings or hooks (`--setting-sources ""`), only jarvisd's MCP server (`--strict-mcp-config`), no built-in tools (`--tools ""`), nothing that can prompt (`--allowedTools mcp__jarvis__*`, `--permission-mode dontAsk`), Jarvis's own `--settings` deny list, an empty working directory under the runtime dir, and `--system-prompt` (the generated rules) instead of Claude Code's coding prompt. Claude Code still keeps its own bookkeeping in `~/.claude*` and uses its login; Jarvis never writes there.

A turn is one JSON envelope in; the model acts through MCP tools and ends with `respond`. jarvisd's MCP server calls `ClaudeCodeBrain.dispatch(policy_name, args)`: `say`/`ask` go to the turn's callbacks, desktop tools to the validated `DesktopClient`, `respond` to the contract gate (one repair, then the spoken fallback). The turn resolves the moment `respond` validates; the model's closing round trip is drained before the next turn. A timeout, a cancelled turn or a dead process drops the session and the next turn starts a fresh one.

## Orchestrator (M1: the voice loop)

`jarvis.orchestrator.Orchestrator` joins the pieces in `jarvis run`. Threading, on purpose:

- **One capture thread** (`capture.Capture`) runs the frame loop: mic frame → `Endpointer` (Silero VAD, 1.5 s pre-roll) → `WakeDetector.score` (about 2.6 % of a core). Only finished `Segment`s (utterance, silence before, peak wake score, "tainted" flag) cross to asyncio, through `call_soon_threadsafe`; the event loop never sees frames.
- **Event loop:** a consumer awaits `Listener.handle(segment)` one segment at a time (STT runs in a worker thread). A wake needs score ≥ `wake.threshold`, ≥ 400 ms of silence before the speech, and the first-word gate (R48). "Jarvis" alone opens a 5 s listen window, `jarvis.ask` an 8 s reply window (R49). Empty transcript → "Sorry, I didn't catch that." (R51).
- **Turn worker:** commands run one at a time as `TurnRunner.run` tasks (fast path, `FastPathDeclined` → brain, speech, activity record). The Stop intent cancels the running turn and speech from the consumer while the loop keeps listening (R21).
- **Deaf while speaking** (R47): `Voice.is_deaf()` is read by the capture thread; segments that overlap Jarvis's own voice plus a 300 ms tail are tainted and ignored. No barge-in in M1.
- **Children** (whisper-server in its own process group, the desktop worker, the claude session, the MCP server) are warmed at start and closed in `components.close_components` on every exit path: end of source, `request_stop`, SIGINT/SIGTERM, a failure.

Every turn (and every dropped trigger) appends one redacted line to `data_dir()/activity/YYYY-MM-DD.jsonl`; files older than `log.retention_days` are purged at start.

## Platform split

Platform-specific code sits beside its interface and is imported only inside its platform branch (the beyondMeetings pattern). Everything above the tool and audio backends is shared. See FRS §9.3 for the capability matrix (Windows, X11, Wayland).

## Reuse

Code is reused from beyondMeetings (`~/meetings/beyondmeetings`) by copying, never as a runtime dependency. The map is in FRS §10.
