# M1 acceptance

Exit criteria (FRS §11, M1): "Jarvis, open/close X", the time and the volume work end to end by voice, and latency is within the §7.1 budget.

Acceptance has two parts:

- **Part A** (this page, done by `scripts/acceptance_m1.py`): synthetic speech played into the **real** pipeline on the dev machine.
- **Part B** (the owner, live mic): the checklist at the end of this page.

Run on 2026-10-14 on branch `feat/m1-t13-acceptance`.

## Environment

| | |
|---|---|
| Machine | Intel Core Ultra 5 225U (14 threads), Linux 7.0.0-34-generic, GNOME on X11, PipeWire 1.0.5, CPU governor `powersave` |
| Python | 3.12.3 |
| VAD / wake | Silero VAD v5 (onnxruntime, 1 thread); stock `hey_jarvis_v0.1` openWakeWord model (dev-only, ruling R67), threshold 0.005 |
| STT | whisper.cpp `whisper-server`, model `ggml-tiny.en`, 4 threads, CPU |
| TTS | Kokoro v1.0 (ONNX), default reply voice `bm_george` |
| Brain | Claude Code 2.1.299, model `sonnet`, mode `balanced` |
| Fixtures | Kokoro voices `am_michael` and `af_heart` (not the reply voice), 16 kHz mono, 1.2 s of leading silence, in `tests/fixtures/acceptance/` (each < 135 KB; `scripts/acceptance_fixtures.py` regenerates them) |
| Home | a scratch `JARVIS_HOME` (never the real one) |
| Playback | the product's PortAudio sink (`SoundDeviceSink`), **with the output latency forced to `high`**. See finding F1: the product's own setting (`low`) stalls on this machine. |
| Starting volume | 58 % (read from `wpctl` at the start of the run; restored at the end and checked: 58 %). Calculator was closed at the end. |

How the run works: one `Orchestrator` with the components `build_components` builds (real VAD, wake model, whisper-server, Kokoro, fast path, desktop worker, Claude Code brain over the MCP server). The only substitutions are the audio source (a `QueueSource` that releases 80 ms frames in real time, like a mic, with silence between fixtures) and a wrapper around the product's sink that notes the time of the first sample of each playback. No HUD window is shown (events are collected instead). Effects are checked independently of Jarvis: Calculator through the X11 window list, the time against the clock, the volume through `wpctl`.

**End of speech** is the last voiced sample of the fixture, so the 700 ms end-of-speech wait is inside every number below, as the FRS "after you stop speaking" wording means. **First audio** is the time the first sample is handed to the sound device; the device's own output latency is not included.

## Results

17 runs, **17 passed**. Two of them were live brain turns (budget: 5).

| Case | Run | Heard | Route | Outcome | EoS→first sound ms | EoS→reply speech ms | STT ms | Action ms | Total ms |
|---|---|---|---|---|---|---|---|---|---|
| open-calculator | 1 | `Jarvis, open calculator.` | fastpath | PASS | 1341 | 2752 | 591 | 653 | 3440 |
| close-calculator | 1 | `Jarvis Close Calculator.` | fastpath | PASS | 1489 | 2255 | 670 | 63 | 2720 |
| open-calculator | 2 | `Jarvis, open calculator.` | fastpath | PASS | 1300 | 2615 | 549 | 602 | 3347 |
| close-calculator | 2 | `Jarvis, close calculator.` | fastpath | PASS | 1351 | 2122 | 564 | 52 | 2714 |
| open-calculator | 3 | `Jarvis, open calculator.` | fastpath | PASS | 1454 | 2777 | 703 | 596 | 3354 |
| close-calculator | 3 | `Jarvis Close Calculator.` | fastpath | PASS | 1463 | 2314 | 638 | 104 | 2856 |
| what-time | 1 | `Jarvis, what time is it?` | fastpath | PASS | 1476 | 2399 | 685 | 1 | 3287 |
| what-time | 2 | `Jarvis, what time is it?` | fastpath | PASS | 1376 | 2332 | 584 | 3 | 3327 |
| what-time | 3 | `Jarvis, what time is it?` | fastpath | PASS | 1386 | 2272 | 594 | 2 | 3250 |
| volume-set-30 | 1 | `Jarvis, set volume to 30%.` | fastpath | PASS | 1260 | 2109 | 576 | 44 | 2964 |
| volume-up | 1 | `Jarvis, volume up.` | fastpath | PASS | 1191 | 2081 | 526 | 57 | 2981 |
| volume-up | 2 | `Jarvis, volume up.` | fastpath | PASS | 1467 | 2786 | 775 | 53 | 3416 |
| volume-up | 3 | `Jarvis, volume up.` | fastpath | PASS | 1240 | 2057 | 572 | 48 | 2936 |
| brain-open | 1 | `Jarvis, please open the calculator app for me.` | brain | PASS | 1289 | 5503 | 564 | 3196 | 7290 |
| brain-close-it | 1 | `Jarvis Close It.` | brain | PASS | 1310 | 4750 | 531 | 2429 | 5402 |
| listen-window | 1 | `Open Calculator.` | fastpath | PASS | 1284 | 2529 | 503 | 609 | 3276 |
| mid-sentence | 1 | `I told Jarvis to open calculator.` | dropped | PASS | - | - | - | - | - |

What each case proved:

- **open/close Calculator, time, volume** (fast path, ×3 with two voices; volume set once): the window appeared / went away, the spoken time was within 2 minutes of the clock, `wpctl` showed 30 % after "set volume to 30 percent" and a higher volume after each "volume up".
- **brain-open / brain-close-it**: "please open the calculator app for me" is not matched by the fast path (route `brain`) and the brain opened Calculator. "close it" has no target of its own; the brain used the previous turn's context and closed it.
- **listen-window**: a bare "Jarvis." produced the chime and opened the listen window; "Open Calculator." said after the window opened ran on the fast path and Calculator opened. (The second utterance was sent once the window had opened, with 1.2 s of its own leading silence, as a person reacting to the chime would.)
- **mid-sentence**: "I told Jarvis to open Calculator." was transcribed, rejected by the first-word rule (logged as a dropped turn), and nothing opened.

## Latency against FRS §7.1

p50 over the 14 passing fast-path runs (brain and dropped excluded). The runs are few (three per command), so read these as indications, not percentiles.

| Stage | Budget p50 / p95 | Measured | |
|---|---|---|---|
| STT (local CPU, tiny.en) | ≤ 1.5 s / 2.5 s | 588 ms (max 775) | within |
| Fast-path action after transcript | ≤ 300 ms / 800 ms | 55 ms; opening an app 600 ms (max 653) | within, except app launch (waits for the window) |
| First audible response after end of speech | ≤ 1.5 s / 2.5 s | 1364 ms (max 1489): the "thinking" earcon | within |
| Reply speech after end of speech | ≤ 1.5 s / 2.5 s | 2323 ms (max 2786) | **over the p50 target and the p95 (max 2786 ms)** |
| Simple brain turn done | ≤ 4 s / 7 s | brain time 3196 ms and 2429 ms; whole turn with speech 7290 ms and 5402 ms | brain within; whole turn includes TTS and playback |
| End-of-speech wait | 700 ms (setting) | 700 ms | as set |

Where the time goes on a fast-path turn (what-time, which has no action cost): 700 ms end-of-speech wait + about 590 ms STT + 2 ms action = about 1.3 s; the reply speech arrives at about 2.3 s, so **text to first sample of Kokoro audio takes about 1.0 s** against the 400 ms TTS budget (p50) . In all 16 turns that produced a sound the first sound after the end of speech was the "thinking" earcon (it plays 1.2 s after speech ended if nothing has been said), not the reply. So the "first audible response" budget is met by the earcon, and the spoken reply is slower than G2 ("feels instant") intends. Cause not investigated; Kokoro on CPU is the obvious suspect.

## Idle CPU against FRS §7.1

Capture, VAD (Silero) and wake scoring over a WAV played at real time, 60 s each, one process, process CPU time over wall time:

| Input | Wall s | Frames | CPU s | % of one core | Segments |
|---|---|---|---|---|---|
| silence | 59.9 | 750 | 5.39 | **9.0** | 0 |
| noise (uniform ±2000) | 59.9 | 750 | 5.12 | **8.5** | 0 |

Budget: ≤ 3 % of one core. **Not met on this machine** (finding F2). For comparison, the same VAD + wake work run back-to-back (not paced) costs about 1.6 % of real time, so most of the real-time cost comes from doing a little work every 80 ms rather than from the work itself; pinning the process to one core, one BLAS thread, or turning off onnxruntime thread spinning did not change it (8.1 to 9 %). The CPU governor is `powersave`; frequency scaling is a plausible cause but was not verified. Only the audio path is counted: whisper-server idles in a separate process and Kokoro/Claude are not running during this measurement.

## Findings

**F1 (blocks Part B on this machine): `SoundDeviceSink` stalls with `latency="low"`.** `src/jarvis/tts/sink.py` opens the output stream with `latency="low"`. On this machine (ALSA default device over PipeWire), `OutputStream.write` stops consuming after a few blocks and never returns: the first spoken reply hangs the speaker thread (and so the turn, which waits for the speech). Reproduced outside Jarvis with plain `sounddevice`:

| `latency=` | 60 writes of 50 ms |
|---|---|
| `"low"` | hung |
| `0.02` | hung |
| `0.05` | ok (3.0 s) |
| `"high"` | ok (3.0 s) |

The acceptance run therefore forces `latency="high"` (option `--output-latency`); with it everything above passed. No product code was changed in this task. A fix (a higher latency, or a callback-based stream) should be decided and tested before the owner runs Part B.

**F2: idle CPU is about 3× the budget** (above).

**F3: reply speech is slower than the budget** (above): about 2.3 s after the end of speech against 1.5 s.

Smaller notes:

- STT heard "Jarvis Close Calculator." and "Jarvis Close It." without the comma on some runs; the gate and the fast path handled both.
- The system volume was changed by something else during this task (0.40, then 1.00, then 0.76, then 0.58, as read at different times), so the run reads the starting volume at the moment it starts and restores that.
- A `phonemizer` warning ("words count mismatch") appears once per run; it comes from Kokoro and did not affect any result.

## Not covered here (Part B)

- A real microphone and room: levels, noise, accents, distance, the 400 ms silence rule with real speakers.
- Echo and self-trigger (FR-ACT-10): Jarvis's own voice is never played into the pipeline here, because the source is a file.
- Real human voices; synthetic voices are cleaner than people.
- Barge-in ("Jarvis, stop") while speech plays (FR-ACT-09), and the latency from stop to silence.
- The HUD window, and the custom wake model (R67): the stock `hey_jarvis` is dev-only; these cases get re-run when the custom model lands.
- Latency percentiles; there are three runs per command.

## Part B: live-mic checklist for the owner

Before you start: read finding F1. If Jarvis goes silent after its first reply and the run seems stuck, that is F1, not you.

1. Install PortAudio (already done on this machine): `sudo apt install libportaudio2`.
2. Fetch the models once: `uv run jarvis models fetch`.
3. Start it: `uv run jarvis run` (add `--no-brain` to skip Claude Code). Say each phrase at normal volume, about an arm's length from the mic, with a short pause before "Jarvis". Wait for the spoken reply before the next.

| # | Say | Expect |
|---|---|---|
| 1 | "Jarvis, open Calculator." | Calculator opens; Jarvis says "Opening Calculator." |
| 2 | "Jarvis, close Calculator." | It closes; "Closed Calculator." |
| 3 | "Jarvis, what time is it?" | The right time, spoken |
| 4 | "Jarvis, volume up." | The volume rises by a step; "Volume N percent." |
| 5 | "Jarvis, set volume to 30 percent." | The volume is 30 %; check with `wpctl get-volume @DEFAULT_AUDIO_SINK@` |
| 6 | "Jarvis, please open the calculator app for me." then, once it has answered, "Jarvis, close it." | The brain opens it (a few seconds), then closes the same window |
| 7 | "Jarvis." (pause until you hear the chime) then "open Calculator." | A chime, then Calculator opens without saying "Jarvis" again; close it by voice |
| 8 | "I told Jarvis to open Calculator." (one sentence, no pause before "Jarvis") | Nothing happens |

Also try, because Part A cannot: say "Jarvis, stop" while Jarvis is talking (it should go quiet at once), and listen for Jarvis triggering on its own voice (it must not).

What to observe: whether each phrase is heard (the HUD or the `[state] text` lines in the terminal show the transcript); how long after you stop speaking you hear something; whether the speakers' own voice ever starts a turn; the CPU use of `jarvis run` at idle in `top` (budget 3 % of a core).

Where to look afterwards: one JSON line per turn in `~/.local/share/jarvis/activity/YYYY-MM-DD.jsonl` (transcript, route, tool calls, stage durations `stt` / `brain` / `total`). Dropped turns are logged with a `drop_reason`. Restore your volume afterwards.

## Reproduce Part A

```
export JARVIS_HOME=/path/to/scratch/home       # holds the models; never your real data
export JARVIS_WHISPER_SERVER=/path/to/whisper-server
uv run jarvis models fetch                      # into that home
uv run python scripts/acceptance_m1.py --out report.md
```

Options: `--no-brain` (skip the two live brain turns), `--no-idle`, `--no-suite`, `--idle-s N`, `--output-latency low|high`, `--verbose`. The run makes noise through the speakers and changes the system volume (it restores it), opens and closes Calculator, and uses two Claude Code turns.
