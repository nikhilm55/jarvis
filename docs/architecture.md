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

## Platform split

Platform-specific code sits beside its interface and is imported only inside its platform branch (the beyondMeetings pattern). Everything above the tool and audio backends is shared. See FRS §9.3 for the capability matrix (Windows, X11, Wayland).

## Reuse

Code is reused from beyondMeetings (`~/meetings/beyondmeetings`) by copying, never as a runtime dependency. The map is in FRS §10.
