# M1 — the voice loop on Linux X11

**Goal:** say "Jarvis, open Calculator" (or close X, the time, volume) on GNOME X11 and hear it done, end to end, within the FRS §7.1 latency budget.
**Done when:** the M1 exit criteria (FRS §11) pass in task 13's acceptance run, with numbers recorded in `docs/milestones/M1-acceptance.md`.
**Stack:** ADR-0010. **Out of scope:** consent prompts, risk tiers above T1, `jarvis.confirm`/`request_access`/`show`, Groq, setup wizard, tray, main window, Windows, Wayland, barge-in while speaking (M2).

## How this plan is run

An **orchestrator session** owns this plan, `docs/handoff.md` and the order of work. Each task below is done by a **worker session** that gets a handoff prompt from the orchestrator (`docs/ai/workflow.md` §Orchestrated work). Workers branch from `main`, keep to their task's files, open one PR (≤ 400 reviewable lines) and end with a REPORT block. The owner merges; the orchestrator updates this plan's status column and the hand-off.

## Interfaces (fixed here so parallel tasks fit together)

Package by capability under `src/jarvis/`. Changing a signature below needs the orchestrator, not a worker.

| Module | Public surface |
|---|---|
| `paths` | `data_dir()`, `config_dir()`, `cache_dir()`, `runtime_dir()`; all honour `JARVIS_HOME` (tests point it at `tmp_path`) |
| `config` | `Settings` (pydantic, one sub-model per capability: `audio`, `wake`, `stt`, `tts`, `brain`, `log`), `load_settings(path: Path \| None = None) -> Settings` from TOML |
| `log` | `get_logger(name)`: JSON lines with rotation under `data_dir()/logs`; `redact(text) -> str` |
| `models` | `ModelSpec(name, url, sha256, filename)`, `REGISTRY: dict[str, ModelSpec]`, `ensure(name) -> Path` (download, verify SHA-256, atomic rename) |
| `audio` | 16 kHz mono int16 **frames of 1280 samples (80 ms)**. `AudioSource` protocol (`frames() -> Iterator[np.ndarray]`, `close()`); `MicSource`, `WavFileSource`. `PreRoll(seconds=1.5)`. `Endpointer(trailing_ms=700, cap_s=30)` emits `SpeechStart(silence_before_ms)` and `Utterance(pcm, started_at, ended_at)` |
| `wake` | `WakeDetector.score(frame) -> float`, `reset()`; `gate(transcript) -> GateResult(accepted: bool, command: str, first_word: str)` (fuzzy rules from M0a table D) |
| `stt` | `Transcriber` protocol: `transcribe(pcm, prompt: str \| None) -> Transcript(text, engine, seconds)`; `WhisperServer` (warm child process) |
| `tts` | `Speaker.say(text) -> SpeechHandle` (`cancel()`, `wait()`, `is_speaking`); `Speaker.earcon(name)` |
| `contract` | pydantic `TurnEnvelope`, `FinalResponse`, `ErrorInfo`; `validate_response(obj) -> FinalResponse` raising `ContractError(problems)`; `sanitise_spoken(text) -> str`; `CONTRACT_VERSION` |
| `policy` | `ToolSpec(name, tier, scopes)`, `gate(tool, args, mode) -> Decision(allowed, reason)`; deny unknown tools; M1 allows T0/T1 with `scopes=()` only |
| `desktop` | `DesktopClient`: `open_app(query)`, `close_app(query)`, `volume_get()`, `volume_set(pct)`, `volume_step(delta)`, `mute(on)`; talks JSON lines to the worker `python -m jarvis.desktop.worker` (ADR-0008) |
| `fastpath` | `match(command) -> Intent \| None`; returns `None` unless certain (FR-NLU-02) |
| `mcp` | `JarvisMcpServer(dispatch)` on `127.0.0.1:<ephemeral>` with a bearer token; `write_client_config(path)` (0600) |
| `brain` | `ClaudeCodeBrain`: `start()`, `turn(envelope, on_say, on_ask) -> FinalResponse`, `reset()`, `close()` |
| `activity` | `ActivityLog.record(TurnRecord)`, 30-day retention |
| `orchestrator` | `Orchestrator.run()`: the FRS §4.2 state machine (M1 subset); emits `HudEvent(state, text)` |
| `hud` | loopback API (`/events` SSE, token, host guard) + pywebview pill window |

## Tasks

| # | Task | Depends on | Model | Status |
|---|---|---|---|---|
| 1 | Foundation: `paths`, `config`, `log`, `models`, CLI subcommands, M1 runtime dependencies | plan merged | Sonnet | todo |
| 2 | `contract`: models, validator, repair message, spoken sanitiser | 1 | Opus | todo |
| 3 | `audio`: mic + WAV sources, pre-roll, Silero VAD endpointer | 1 | Sonnet | todo |
| 4 | `stt`: warm whisper-server transcriber + model benchmark | 1 | Sonnet | todo |
| 5 | `tts`: Kokoro streaming speaker, earcons, fallback | 1 | Sonnet | todo |
| 6 | `desktop` worker, M1 subset + `policy` stub gate | 1 | Opus | todo |
| 7 | `wake`: ONNX detector (parity with M0a scores) + first-word gate | 3 | Sonnet | todo |
| 8 | `fastpath`: open/close app, time/date, volume, stop | 6 | Sonnet | todo |
| 9 | `mcp`: jarvisd MCP server with contract + desktop tools via the gate | 2, 6 | Opus | todo |
| 10 | `brain`: warm Claude Code session, rules prompt, contract repair | 9 | Opus | todo |
| 11 | `orchestrator` + `activity`: the turn loop, `jarvis run` | 4, 5, 7, 8, 10 | Opus | todo |
| 12 | `hud`: loopback events API + pywebview pill (frozen design) | 11 | Sonnet | todo |
| 13 | Acceptance: scripted WAV runs + owner's live run, latency report | 12 | Sonnet | todo |
| W | Custom "Jarvis" wake model (dev tool in `tools/wakeword/`, not shipped code) | plan merged | Sonnet | todo |

**Waves:** 1 → {2, 3, 4, 5, 6, W} in parallel → {7, 8, 9} → 10 → 11 → 12 → 13. Track W runs alongside everything and lands before 13.

### Verify per task

1. `uv run jarvis --help` lists `run`, `say`, `listen`, `models`; `uv run jarvis models fetch --dry-run` prints the registry; tests cover TOML loading, `JARVIS_HOME`, redaction and SHA-256 mismatch → error.
2. Tests: every FRS §5.6.3 example validates; failed-without-remedy, markdown/URL/emoji in `spoken` and unknown `status` are rejected or sanitised as FR-IO-01…03 say.
3. Tests on synthetic WAV fixtures: pre-roll keeps the first 1.5 s; trailing silence 700 ms ends the utterance; 30 s cap; `silence_before_ms` is reported. Manual: `uv run jarvis listen --once` prints the utterance length.
4. Integration test (skipped when the binary is absent) transcribes a fixture; `scripts/bench_stt.py` prints p50/p95 for tiny.en/base.en/small.en on 3 s clips; the default is the largest model with p50 ≤ 800 ms on the dev machine.
5. `uv run jarvis say "Opening Calculator."` speaks; time to first audio ≤ 400 ms printed; `cancel()` silences within 300 ms (test with a fake output device).
6. Worker tests with a fake backend; real run opens and closes Calculator 10/10; a killed worker is restarted and the call retried once; `gate()` denies unknown tools and any tool with scopes.
7. Detector scores match `openwakeword` 0.6.0 on 50 M0a clips within 1e-3; gate tests reproduce M0a table D's decisions on the cached transcripts.
8. Table-driven tests: ≥ 40 phrasings; ambiguous ones return `None`; every intent goes through `gate()`.
9. Test client lists exactly the M1 tools; a call without the token is rejected; a denied tool returns a tool error, not an exception.
10. Live test (marked, skipped in CI): 10 warm turns "open Calculator" via the brain, p50 ≤ 4 s; built-in tools unavailable (asking it to run `ls` fails safely); a malformed final response triggers exactly one repair.
11. Fake-component tests for every M1 state transition (wake → gate drop, "Jarvis" alone → 5 s listen, `jarvis.ask` → 8 s reply window, deaf while speaking); `jarvis run --source fixture.wav` completes a turn; one activity record per turn.
12. HUD shows idle/listening/transcript/thinking/acting/speaking/error with the frozen tokens; auto-hides after 4 s; API rejects a wrong token or Host header.
13. Scripted runs of the exit-criteria commands from WAV fixtures plus the owner's live run; a latency table against §7.1; idle CPU ≤ 3% of one core.
W. Trained model beats the stock pipeline on the M0a set (recall ≥ 94.3% for "Jarvis, …", 0 false accepts in 60 min, sound-alikes ≤ 1%) using **held-out voices** not seen in training; model file + SHA-256 registered in `models`.
