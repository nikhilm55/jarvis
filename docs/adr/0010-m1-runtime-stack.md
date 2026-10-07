# 0010 — M1 runtime stack for the voice loop

- **Status:** Accepted (2026-10-07)
- **Deciders:** @nikhilm55
- **Refs:** FRS §5.1–5.7, §9.2, §7.1; M0a/M0b/M0c cards; ADR-0003, ADR-0004, ADR-0008

## Context

M1 turns the M0 spikes into the first product code: mic → wake word → VAD → STT → brain → contract → TTS on GNOME X11. FRS §9.2 lists recommended components "to be confirmed in M0". M0 confirmed the architecture but surfaced constraints: the `openwakeword` package pulls in tflite/scipy/scikit-learn and its stock models are licensed CC BY-NC-SA 4.0; Claude Code ships built-in tools (Bash, Edit…) that must not be reachable from a voice command; native desktop bindings crash on teardown (ADR-0008).

## Options

1. Use each upstream package as-is (`openwakeword`, `whisper-cli` per clip, Claude Code with its default tools, desktop calls in-process).
2. Use the same models through thin, owned wrappers with warm processes and a single tool surface.

## Decision

Option 2:

| Concern | M1 choice |
|---|---|
| Wake word | openWakeWord **ONNX models run directly with onnxruntime** (melspectrogram → embedding → classifier). No `openwakeword` package. The stock `hey_jarvis` model is for development only; a custom single-word "Jarvis" model (trained in M1 track W) replaces it before any distribution. |
| VAD | Silero VAD ONNX via onnxruntime. |
| STT | **whisper.cpp `whisper-server`** as a warm child process, clips POSTed as in-memory 16 kHz WAV, `prompt` biasing with "Jarvis". Groq is optional and deferred until the setup wizard can hold the key (FRS D16). |
| Brain | Claude Code warm stream-json session with `--tools ""` (no built-in tools), `--strict-mcp-config` pointing only at **jarvisd's own MCP server** (loopback streamable HTTP, bearer token, config file mode 0600), and `--settings` with no user hooks. |
| Tool surface | One MCP server in jarvisd exposes the I/O contract tools (`jarvis.say`, `jarvis.ask`, `jarvis.respond`) and the M1 desktop subset (apps open/close, volume). Every handler, and the fast path, calls the same policy gate (ADR-0004); in M1 the gate is deny-by-default with an allowlist of T0/T1 tools that touch no personal scope. |
| Desktop | The ADR-0008 worker, M1 subset only. |
| TTS | Kokoro via `kokoro-onnx`, streamed per sentence; `spd-say` fallback. |
| Models | Downloaded on demand into the user data dir by `jarvis models fetch`, each pinned by URL and SHA-256. Never committed. |

## Consequences

- Easier: small dependency tree that installs on Python 3.11 and 3.12; no model cold starts per turn; the brain physically cannot run shell commands in M1.
- Harder: we own ~100 lines of wake-word feature extraction that must match upstream scores (verified against the M0a clips).
- Must be true: no tool is reachable except through jarvisd's MCP server and the policy gate; licences of shipped models and libraries (stock wake model, espeak-ng via Kokoro's phonemizer) are settled under OQ-004 before distribution.
