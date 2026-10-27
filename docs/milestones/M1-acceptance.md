# M1 acceptance

Exit criteria (FRS §11, M1): "Jarvis, open/close X", the time and the volume work end to end by voice, and latency is within the §7.1 budget.

Acceptance has two parts:

- **Part A** (this page, done by `scripts/acceptance_m1.py`): synthetic speech played into the **real** pipeline on the dev machine.
- **Part B** (the owner, live mic): the checklist at the end of this page.

First run 2026-10-14 on branch `feat/m1-t13-acceptance`; re-run the same day on `feat/m1-t13f-fixes` after the fixes for findings F1 and F2 (Task 13F). The numbers below are from the re-run; the first run's are kept where they show what changed.

## Environment

| | |
|---|---|
| Machine | Intel Core Ultra 5 225U (14 threads), Linux 7.0.0-34-generic, GNOME on X11, PipeWire 1.0.5, CPU governor `powersave` |
| Python | 3.12.3 |
| VAD / wake | Silero VAD v5 (onnxruntime, 1 thread); stock `hey_jarvis_v0.1` openWakeWord model (dev-only, ruling R67), threshold 0.005, run only while the VAD hears speech (finding F2) |
| STT | whisper.cpp `whisper-server`, model `ggml-tiny.en`, 4 threads, CPU |
| TTS | Kokoro v1.0 (ONNX), default reply voice `bm_george` |
| Brain | Claude Code 2.1.299, model `sonnet`, mode `balanced` |
| Fixtures | Kokoro voices `am_michael` and `af_heart` (not the reply voice), 16 kHz mono, 1.2 s of leading silence, in `tests/fixtures/acceptance/` (each < 135 KB; `scripts/acceptance_fixtures.py` regenerates them) |
| Home | a scratch `JARVIS_HOME` (never the real one) |
| Playback | the product's PortAudio sink (`SoundDeviceSink`) with the product's own default output latency (`high`); nothing is patched. The first run had to force `high` because the then-default `low` stalled (finding F1). |
| Starting volume | 58 % (read from `wpctl` at the start of the run; restored and read back at the end: 58 %). Calculator was verified closed after the run. |

How the run works: one `Orchestrator` with the components `build_components` builds (real VAD, wake model, whisper-server, Kokoro, fast path, desktop worker, Claude Code brain over the MCP server). The only substitutions are the audio source (a `QueueSource` that releases 80 ms frames in real time, like a mic, with silence between fixtures) and a wrapper around the product's sink that notes the time of the first sample of each playback. No HUD window is shown (events are collected instead). Effects are checked independently of Jarvis: Calculator through the X11 window list, the time against the clock, the volume through `wpctl`.

**End of speech** is the last voiced sample of the fixture, so the 700 ms end-of-speech wait is inside every number below, as the FRS "after you stop speaking" wording means. **First audio** is the time the first sample is handed to the sound device; the device's own output latency is not included.

## Results

17 runs, **17 passed**. Two of them were live brain turns (the script now refuses a live brain turn outside the brain cases and after five).

| Case | Run | Heard | Route | Outcome | EoS→first sound ms | EoS→reply speech ms | STT ms | Action ms | Total ms |
|---|---|---|---|---|---|---|---|---|---|
| open-calculator | 1 | `Jarvis, open calculator.` | fastpath | PASS | 1414 | 2624 | 544 | 620 | 3360 |
| close-calculator | 1 | `Jarvis Close Calculator.` | fastpath | PASS | 1494 | 2437 | 687 | 62 | 2880 |
| open-calculator | 2 | `Jarvis, open calculator.` | fastpath | PASS | 1257 | 2418 | 519 | 470 | 3183 |
| close-calculator | 2 | `Jarvis, close calculator.` | fastpath | PASS | 1354 | 2217 | 560 | 57 | 2808 |
| open-calculator | 3 | `Jarvis, open calculator.` | fastpath | PASS | 1469 | 2717 | 713 | 602 | 3288 |
| close-calculator | 3 | `Jarvis Close Calculator.` | fastpath | PASS | 1466 | 2293 | 654 | 83 | 2769 |
| what-time | 1 | `Jarvis, what time is it?` | fastpath | PASS | 1322 | 2211 | 530 | 2 | 3319 |
| what-time | 2 | `Jarvis, what time is it?` | fastpath | PASS | 1319 | 2193 | 535 | 2 | 3305 |
| what-time | 3 | `Jarvis, what time is it?` | fastpath | PASS | 1358 | 2233 | 567 | 2 | 3305 |
| volume-set-30 | 1 | `Jarvis, set volume to 30%.` | fastpath | PASS | 1231 | 2193 | 544 | 44 | 3083 |
| volume-up | 1 | `Jarvis, volume up.` | fastpath | PASS | 1219 | 2047 | 548 | 54 | 2930 |
| volume-up | 2 | `Jarvis, volume up.` | fastpath | PASS | 1245 | 2075 | 551 | 61 | 2934 |
| volume-up | 3 | `Jarvis, volume up.` | fastpath | PASS | 1213 | 1948 | 547 | 43 | 2854 |
| brain-open | 1 | `Jarvis, please open the calculator app for me.` | brain | PASS | 1379 | 5426 | 567 | 3269 | 6381 |
| brain-close-it | 1 | `Jarvis Close It.` | brain | PASS | 1323 | 4683 | 539 | 2601 | 5796 |
| listen-window | 1 | `Open Calculator.` | fastpath | PASS | 1351 | 2640 | 567 | 575 | 3322 |
| mid-sentence | 1 | `I told Jarvis to open calculator.` | dropped | PASS | - | - | - | - | - |

What each case proved:

- **open/close Calculator, time, volume** (fast path, ×3 with two voices; volume set once): the window appeared / went away, the spoken time was within 2 minutes of the clock, `wpctl` showed 30 % after "set volume to 30 percent" and a higher volume after each "volume up".
- **brain-open / brain-close-it**: "please open the calculator app for me" is not matched by the fast path (route `brain`) and the brain opened Calculator. "close it" has no target of its own; the brain used the previous turn's context and closed it.
- **listen-window**: a bare "Jarvis." produced the chime and opened the listen window; "Open Calculator." said after the window opened ran on the fast path and Calculator opened. (The second utterance was sent once the window had opened, with 1.2 s of its own leading silence, as a person reacting to the chime would.)
- **mid-sentence**: "I told Jarvis to open Calculator." was transcribed, rejected by the first-word rule, and nothing opened. The case now passes only if the activity log has a dropped record with the first-word reason; before, it also passed if the pipeline heard nothing.

## Latency against FRS §7.1

p50 over the 14 passing fast-path runs (brain and dropped excluded). The runs are few (three per command), so read these as indications, not percentiles; the "max" column is the largest of 14 runs, not a p95. The reference point (the last voiced sample of the fixture) is about 80 ms earlier than where a real endpointer would put it, which flatters nothing but should be kept in mind.

| Stage | FRS §7.1 target p50 / p95 | Measured | |
|---|---|---|---|
| STT (local CPU, tiny.en) | ≤ 1.5 s / 2.5 s | 550 ms (max 713) | within |
| Fast-path action after transcript | ≤ 300 ms / 800 ms | 49 ms; opening an app 589 ms (max 620) | within, except app launch (it waits for the window) |
| First audible response after end of speech | ≤ 1.5 s / 2.5 s | 1337 ms (max 1494): the "thinking" earcon | within, with the caveat below |
| Simple brain turn done | ≤ 4 s / 7 s | brain time 3269 ms and 2601 ms; whole turn including the spoken reply 6381 ms and 5796 ms | brain time within; read as the whole turn it is over the p50 and within the p95. §7.1 does not say which is meant |
| TTS time to first audio (local) | ≤ 400 ms / 800 ms | about 600 to 660 ms warm, measured on its own (below) | **over the p50, within the p95** |
| End-of-speech wait | 700 ms (setting) | 700 ms | as set |

The reply speech arrives about 2.2 s after the end of speech (p50 2225 ms, max 2717). §7.1 has no budget for that figure, so it is reported without a verdict. It is a **composite**, not TTS time: 700 ms end-of-speech wait, about 550 ms STT, the fast-path action, then the reply speech starts. On fast-path turns STT finishes about 1.3 s after the end of speech, which is after the 1.2 s "thinking" earcon has fired, so the reply is queued behind the earcon job (the speaker runs jobs one at a time: open the stream, play 110 ms, close it) before Kokoro even starts. The two suspects for the extra time are therefore the earcon queue and the sink's output latency (`high`, 35 ms), plus Kokoro itself.

TTS measured on its own (Task 13F, warm engine, real sink, `Speaker.say` to `first_audio_s`): 663, 627, 598 and 658 ms for four short replies; the Kokoro synthesis alone (no sink) takes 595 to 664 ms. A reply queued behind an earcon took 779 ms to its first sample: the earcon job adds about 130 ms. So Kokoro on CPU misses the 400 ms TTS target by about 200 to 260 ms; that is a finding for a later task (a smaller or quantised voice, or sentence-level streaming of the first clause), not part of this one. (`jarvis say` reports about 1.9 s because it also loads the engine in a new process.)

Caveat on the first-audible verdict: in 16 of 17 turns the first sound was the earcon, which plays on a 1.2 s timer if nothing has been said. The budget is met by the earcon, not by an answer; the spoken reply is slower than G2 ("feels instant") intends.

## Idle CPU against FRS §7.1

The path measured is: a WAV file played at real time by `WavFileSource` (not the PortAudio microphone, whose callback thread is not counted), then the product's capture chain (`build_segmenter`: Silero VAD, endpointer and the wake detector), 60 s each, one process, process CPU time over wall time. whisper-server idles in a separate process; Kokoro and Claude are not running.

| Input | Wall s | Frames | CPU s | % of one core | Segments |
|---|---|---|---|---|---|
| silence | 59.9 | 750 | 1.66 | **2.78** | 0 |
| noise (uniform ±2000) | 59.9 | 750 | 1.38 | **2.30** | 0 |

Budget: ≤ 3 % of one core. **Met, with a thin margin on silence** (two other 60 s runs of the same code gave 2.64 and 2.72 for silence, 2.47 and 2.35 for noise). Before the fix the same measurement gave 9.0 % and 8.5 % (see F2). Nearly all of what is left is the Silero VAD model, which has to run on every window to find speech; it takes about 0.2 ms per frame when run back to back and about 1.9 ms between paced frames. A mic adds a PortAudio callback thread that is not in this number.

## Findings

**F1 (fixed, Task 13F): `SoundDeviceSink` stalled with `latency="low"`.** The sink opened the output stream with `latency="low"`. On this machine (ALSA default device over PipeWire), `OutputStream.write` stops consuming after a few blocks and never returns: the first spoken reply hung the speaker thread (and so the turn, which waits for the speech). Reproduced outside Jarvis with plain `sounddevice`:

| `latency=` | 60 writes of 50 ms |
|---|---|
| `"low"` (8.7 ms) | hung (and the writer thread stays blocked even after `abort()`) |
| `0.02` | hung |
| `0.05` | ok (3.0 s) |
| `"high"` (34.7 ms) | ok (3.0 s); also at 16, 22.05, 24 and 44.1 kHz, three runs each |

Fix: `[tts] output_latency` (default `"high"`, or a number of seconds) is passed to the stream, and every stream call runs behind a timeout, so a write that does not return in 2 s aborts the stream and fails the speech handle (`audio output stalled`) instead of hanging the speaker thread; the next utterance opens a new stream. Measured on this machine with the real device (`Speaker` plus `SoundDeviceSink`, a 2 s quiet tone, six runs): cancel to the sink's `abort()` returning is a median 19 ms (max 23 ms), and the device holds 35 ms, so cancel to silence is estimated at about 55 ms (the sum of the two; the moment the sound stops was not recorded) against the 300 ms target. First audio (first write) is about 25 ms after `say()` with a tone engine; `high` adds 26 ms of device latency over `low` (8.7 ms) to when it is heard. The acceptance run now uses the product default with nothing patched.

**F2 (fixed, Task 13F): idle CPU was 9 % of a core.** The cause, with the numbers behind it:

| Hypothesis | Test | Result |
|---|---|---|
| The same work costs 9 % | unpaced, 250 frames of VAD + wake | 0.35 s of CPU, 1.4 ms/frame, **1.75 %**. The code is not 9 %. |
| ONNX Runtime thread pools spin between frames | `allow_spinning=0` on the intra- and inter-op pools | 8.95 % vs 9.43 % (noise). Sessions already use 1 thread. **Rejected.** |
| Memory arena or graph optimisation level | `arena=0, mempat=0`; `opt=99` | 9.19 %; 8.34 %. **Rejected.** |
| Thread wake-ups and the pacing loop | a paced loop that does no work | 0.59 %. Not the cause. |
| Python glue (numpy buffers) | per-component timing | 0.41 ms/frame paced vs 0.03 hot. Real but small. |
| **The core is slow because it is idle between frames** | per-frame time of the same call: paced 6.4 ms, unpaced 1.4 ms; core clock during the paced run 1.0 to 1.3 GHz against 4.8 GHz max (`powersave`, intel_pstate) | **Verified.** The same call is 4.6× slower when it runs alone every 80 ms. A busy loop that keeps the core hot cut it to 2.3 ms. A spinner on another core did nothing (5.5 vs 6.0 ms), so it is the core's own state. |
| Where the paced time goes | per component | wake 7.2 % (embedding model 3.9 ms of 5.2 ms/frame), VAD 3.0 %, pacing 0.6 % |
| Batching frames to wake the core less often | 2, 4, 8 frames per burst | 8.2, 7.3, 5.5 %. Helps a little, costs up to 640 ms; **rejected.** |

Fix: the machine's idle clocking cannot be changed from the product, so the work had to shrink. The wake score is only read while an utterance is open, so `WakeDetector` takes a `hot` callable (the product passes `Endpointer.speaking`). While not hot a frame is only remembered; the first hot frame replays the last 28 remembered frames from the raw audio, which reproduces the 16 embeddings the classifier reads exactly, and returns the max of its own score and the scores of the two frames just before it (the frames the segmenter's peak already counted). Checked three ways: a lazy and an always-on detector gave identical scores on the hot frames over random gaps of 0 to 100 frames on real audio (max diff 0 for the replay; 12 frames of memory instead of 28 gave 0.49); the **segment wake scores of 100 M0a clips through the real endpointer are identical** (max diff 0); `scripts/check_wake_parity.py` (50 clips) gives max abs diff 3.92e-05, the same as before, and GATE PASS. A first version without the look-back changed the segment wake score of many clips (by up to 0.22), because the peak often sits in the one or two frames before the VAD fires; the segment-level check caught it.

**F3 (reworded, not fixed here): the reply speech is slow** (latency section above): about 2.2 s after the end of speech is a composite of the earcon queue, the sink latency and Kokoro's own 600 to 660 ms against a 400 ms TTS target.

Smaller notes:

- STT heard "Jarvis Close Calculator." and "Jarvis Close It." without the comma on some runs; the gate and the fast path handled both.
- The system volume was changed by something else during this task (0.40, then 1.00, then 0.76, then 0.58, as read at different times), so the run reads the starting volume at the moment it starts and restores that.
- A `phonemizer` warning ("words count mismatch") appears once per run; it comes from Kokoro and did not affect any result.

## Not covered here (Part B)

- A real microphone and room: levels, noise, accents, distance, the 400 ms silence rule with real speakers.
- Echo and self-trigger (FR-ACT-10): Jarvis's own voice is never played into the pipeline here, because the source is a file.
- Real human voices; synthetic voices are cleaner than people.
- Barge-in ("Jarvis, stop" while speech plays, FR-ACT-09) is M2: M1 is deaf while Jarvis speaks (R47), so it cannot be tried. Only the sink's cancel-to-silence time was measured (estimated at about 55 ms, finding F1).
- The HUD window, and the custom wake model (R67): the stock `hey_jarvis` is dev-only; these cases get re-run when the custom model lands.
- Latency percentiles; there are three runs per command.

## Part B: live-mic checklist for the owner

Before you start:

- The sink stall (F1) is fixed: the product's default output latency is now `high` and a stalled write fails the speech after 2 s instead of hanging. If Jarvis still goes silent after a reply, look for "audio output stalled" in the log; `[tts] output_latency` in `config.toml` can be set to a number of seconds.
- The wake model is the stock dev `hey_jarvis_v0.1` (ruling R67). A phrase that is not picked up may be that model, not a bug; the custom model is track W and these cases get re-run when it lands.
- The brain phrases (6) need a logged-in Claude Code. Without one, start with `--no-brain` and skip 6.

1. Install PortAudio (already done on this machine): `sudo apt install libportaudio2`.
2. Fetch the models once: `uv run jarvis models fetch`.
3. whisper-server must be found: set `JARVIS_WHISPER_SERVER` to its path, or have `whisper-server` on `PATH`.
4. Start it: `uv run jarvis run`. Add `--no-brain` to skip Claude Code and `--no-hud` for no on-screen pill (useful over a remote session). Say each phrase at normal volume, about an arm's length from the mic, with a short pause before "Jarvis". Wait for the spoken reply before the next.

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

Also try, because Part A cannot: ask for something slow (for example "Jarvis, what is on my screen right now") and say "Jarvis, stop" (or "cancel") while Jarvis is still thinking or acting, before it speaks; the turn should end with a single chime and no spoken answer. Jarvis is deaf while it speaks (R47), so "stop" cannot interrupt speech until barge-in arrives in M2. Also confirm Jarvis does not trigger on its own voice: let it speak a long answer and check no new turn starts.

What to observe: whether each phrase is heard (the HUD or the `[state] text` lines in the terminal show the transcript); how long after you stop speaking you hear something; whether the speakers' own voice ever starts a turn; the CPU use of `jarvis run` at idle in `top` (budget 3 % of a core).

Where to look afterwards: one JSON line per turn in `~/.local/share/jarvis/activity/YYYY-MM-DD.jsonl` (transcript, route, tool calls, stage durations `stt` / `brain` / `total`). Dropped turns are logged with a `drop_reason`. Restore your volume afterwards.

## Reproduce Part A

```
export JARVIS_HOME=/path/to/scratch/home       # holds the models; never your real data
export JARVIS_WHISPER_SERVER=/path/to/whisper-server
uv run jarvis models fetch                      # into that home
uv run python scripts/acceptance_m1.py --out report.md
```

Options: `--no-brain` (skip the two live brain turns), `--no-idle`, `--no-suite`, `--idle-s N`, `--output-latency low|high|SECONDS` (default: the product setting), `--verbose`. The run makes noise through the speakers and changes the system volume (it restores it), opens and closes Calculator, and uses two Claude Code turns (it refuses a third outside the brain cases and any after five).

## Part B results (owner, live mic, 2026-10-14)

A partial run: the owner talked to `jarvis run` freely for about an hour instead of working through the checklist in order. Product defaults, scratch `JARVIS_HOME`, stock `hey_jarvis` wake model.

| What was tried | Result |
|---|---|
| Two-step wake (checklist 7): "Jarvis." → chime → "Open calculator." | **Pass.** Calculator opened, "Opening Calculator." |
| Brain turns (6 of them): the time, an unclear request, "help me set up my project", "open the terminal and check what I've been working on", an off-task request | **Pass.** Each got a sensible short answer. The terminal opened; Jarvis said truthfully that it can't run commands or create files (M2 scope). The off-task request was declined politely. Brain time 1.5–3.6 s. |
| Follow-up replies without "Jarvis" (reply window, R60) | **Pass.** Twice. |
| Speech mid-sentence or not starting with "Jarvis" (checklist 8 behaviour) | **Pass.** 13 turns dropped silently: 11 "gate rejected the first word", 2 "silence_before_ms<400". |
| Idle CPU of `jarvis run` with a real mic in a real room | **3.7 % of one core** over 60 s (budget 3 %; Part A, with a file source: 2.7 %). HUD and whisper-server ≈ 0 %. |
| Checklist 1–5, 6's "close it", "Jarvis, stop" while thinking, self-trigger on a long answer | Not tried. |

Findings (carried into the M2 backlog in `docs/handoff.md`):

- **B1. The brain calls the owner by the Linux account's full name.** That field holds a placeholder ("55"), and every brain reply used it. Jarvis's code never reads it; Claude Code passes it to the model. Fix: a "your name" setting fed to the brain, and an instruction not to use the account name when none is set.
- **B2. A possible false wake is apologised for out loud.** Twice the wake word fired, speech-to-text returned nothing, and Jarvis said "Sorry, I didn't catch that." to an empty room. An empty transcript straight after a wake should end silently (or with the soft chime).
- **B3. A polite refusal shows as an error.** The off-task decline put the HUD in its error state. A decline is not a failure.
- **B4. Idle CPU 3.7 % with a real mic** (over the 3 % budget). Likely room noise keeping the VAD busy, which runs the wake models (finding F2's lazy wake). Measure the share of frames the VAD marks as speech in a quiet room before tuning.
- **B5. `tiny.en` mishears real speech** ("what time is it" became "what is the time rate now"; one longer sentence was garbled). The brain recovered both times, but the fast path missed. Levers: try `base.en` against the latency budget; the custom wake model (track W) changes what reaches STT.

## Task 13 (M2) follow-up (2026-10-16)

Fixes for B2 to B5 and the reply latency, measured on the same machine as Part A. The host was shared with other jobs (load average 3 to 17), so every absolute time below is roughly 1.5 to 2 times slower than the quiet-machine Part A numbers (STT p50 about 1.1 s here, 0.55 s there). Compare the before and after columns of one table with each other, not with Part A. Scratch `JARVIS_HOME`, no microphone (files and synthetic audio only), volume read at the start and restored (1.00 before and after).

### B2 and B3: fixed

- **B2.** An empty transcript right after a wake word now ends the turn silently: no apology, no chime, no HUD change. It is still logged with `drop_reason: "empty transcript"`. A non-empty transcript the gate rejects is unchanged (silent drop, `gate rejected the first word`). An empty transcript while Jarvis is waiting for the user (the listen window after a bare "Jarvis", or a reply to its question) still says "Sorry, I didn't catch that.", because there the user expects an answer. FRS FR-STT-07 and `docs/architecture.md` say so. Tests: `tests/test_orchestrator_listener_drops.py::test_should_end_silently_when_transcript_is_empty_right_after_a_wake` (and the whitespace-only and gate-rejected cases beside it) pin the wake window; the unchanged apology in the listen and reply windows is pinned by `tests/test_orchestrator_listener_windows.py` (`..._when_transcript_is_empty_in_listen_window`, `test_should_keep_reply_window_open_when_transcript_is_empty`).
- **B3.** The turn code was already right: `HudEvent("error", ...)` is only sent for `status == "failed"` with an `ErrorInfo` (`turns.py`, `_finish`). The off-task decline came back from the brain as `failed`. The brain rules now say: "Declining an off-task or impossible request is status success. A policy, consent or cancel block is status failed with its error code (BLOCKED_BY_POLICY, CONSENT_DENIED, CANCELLED)." The second sentence keeps a real block a failure with its code in the log (FR-CON-08). The rules stay within their 3000-character cap, and the list of 15 error codes is unchanged. Tests: `tests/test_brain_rules.py` pins both sentences and the code list; `tests/test_orchestrator_turns_decline.py` checks that `success`, `needs_input` and `partial` replies never reach the error state and that a real `failed` still does.

### B4: idle CPU (no code change found; needs the owner's room)

`uv run python scripts/acceptance_idle.py` now feeds looped synthetic room noise (pink noise at -50 dBFS plus clicks at -35 dBFS, generated at run time, 15 s looped) through the product's capture chain in real time, and reports CPU and the share of VAD windows marked as speech.

| Input (60 s each) | CPU, % of one core | VAD windows | Marked speech |
|---|---|---|---|
| room noise | 2.99, 3.04 | 1875 | 0.0 % |
| silence | 2.93 | 1875 | 0.0 % |

Earlier 20 to 30 s runs ranged from 2.5 to 3.8 % for the same input (the file-source run of Part A: 2.7 %). So on this input idle CPU is at the 3 % budget, and it does not depend on the input: the VAD never calls the noise speech, so the wake models stay off (lazy wake works). The cost is the always-on Silero VAD:

- `cProfile` of the frame loop: onnxruntime `run` is 0.79 s of 1.10 s CPU over 30 s (72 %); the wake detector, endpointer and pre-roll together are under 0.1 s.
- The model costs 0.13 ms per window in a tight loop but 0.8 to 1.3 ms per window when it runs once per 80 ms frame with the core asleep in between (CPU governor `powersave`, cold caches). Session options (graph level, memory arena, memory pattern, spinning, thread count) and batching two frames per wake-up made no difference beyond the 2.2 to 4.2 % run-to-run spread, so nothing was changed: any real fix would delay speech detection or change the VAD.
- **Open (task 14):** the owner's 3.7 % with a real mic is inside that spread and cannot be separated from it here. It needs one quiet-room measurement on the owner's machine: `uv run python scripts/acceptance_idle.py --seconds 60 --profile` for the baseline, then `top` on `jarvis run`.

### B5: `tiny.en` against `base.en`

`uv run python scripts/bench_stt.py --models tiny.en base.en --count 60`: 14 acceptance fixtures (Kokoro voices) and 60 M0a `jarvis_command` clips (Piper voices with noise; the manifest text is the reference), the product wake prompt, 4 threads, warm server.

| Model | Clips | p50 ms | p95 ms | p50 on 2.5 to 3.5 s clips | "Jarvis" first | WER acceptance | WER M0a |
|---|---|---|---|---|---|---|---|
| tiny.en | 74 | 1152 | 1478 | 1101 | 100 % | 0.0 % | 4.1 % |
| base.en | 74 | 2450 | 3022 | 2426 | 95.8 % | 0.0 % | 2.2 % |

With 8 threads (34 clips): tiny.en 718 ms p50, base.en 1548 ms, WER M0a 2.0 % against 1.0 %. The quiet-machine figures from R29 were 572 ms and 1392 ms.

**The default stays `tiny.en`:** `base.en` misses the 800 ms p50 budget (FRS 7.1) on 3 s clips even on a quiet machine, with 4 or 8 threads. It does halve the word errors on noisy synthetic speech, and the synthetic fixtures cannot reproduce the real-voice misses of B5 (both models score 0 % on the clean fixtures), so the real-voice comparison is still open: say the B5 phrases to both models in task 14 (`stt.model = "base.en"` in `config.toml`).

### Reply latency

`scripts/acceptance_m1.py --no-brain` (15 runs each time, all pass), pooled over two runs before and three after, end of speech to first reply speech:

| | Before (28 turns) | After (42 turns) |
|---|---|---|
| End of speech to reply speech, p50 | 3921 ms | 3725 ms |
| of which after STT, p50 | 2760 ms | 2597 ms |
| Turns that answer in under 200 ms of action: after STT, p50 | 2485 ms | 2485 ms |
| First sound was the thinking earcon | 14 of 15 (both runs) | 11, 11 and 4 of 15 |

What changed in the measured run (the 3-run "after" set): the thinking earcon was cut the moment a reply, a progress line or a question was ready, and waited at least 0.3 s after the turn started. Review round 1 removed the 0.3 s wait: the earcon is now scheduled exactly by FR-TALK-02 (end of speech + 1.2 s, never after reply speech has started, cut when a reply is ready), so a turn answered inside 1.2 s has no ack sound before its reply. The latency numbers above were taken with the 0.3 s wait and were not re-measured (no audio this round); the 0.3 s only moved when the earcon played on fast-path turns, not the reply time, so the end-to-end gain is expected to be unchanged. Gain on this loaded machine: about 160 ms overall and none for quick actions, because most of the time is Kokoro and STT (the earcon only ever cost its own 110 ms plus the sink open and close).

TTS first audio for `bm_george` (warm, `Speaker` with a null sink, 5 sentences, 8 repeats; load 4 to 15):

| Reply | Before p50 | After p50 |
|---|---|---|
| "Opening Calculator." (19 chars) | 1463 ms | 1255 ms |
| "Volume 40 percent." | 1425 ms | 1278 ms |
| "Done. I opened Calculator and set ..." (70 chars) | 690 ms | 629 ms |
| "I can't run commands or create files yet. That arrives ..." (124 chars) | 2034 ms (2435, 2149 in other runs) | 1285 ms (1517, 1409) |
| All, p50 / p95 | 1438 / 2197 ms | 1265 / 1873 ms |

The "After" column of this table was measured with the first version of the cut (four words when there was no clause mark). The row for "I can't run commands or create files yet." no longer applies: that sentence has no clause mark and now stays whole, so it starts like the "Before" figure. The clause-cut figures are in the `bench_tts.py` table below.

Kokoro takes about 0.4 s plus 0.6 s per second of audio under this load, all of it inside the onnxruntime call (`cProfile`); intra-op thread counts 2 to 8 made no difference. So the first chunk is made short: `split_for_speech` cuts a long first sentence after its first clause mark (comma, semicolon, colon or dash within six words). Review round 1 removed an earlier four-word cut with no mark, because it could leave dead air while the rest was synthesised (synthesis runs one chunk ahead of playback).

`scripts/bench_tts.py` (real Kokoro, silent sink, no audio played) reports first audio, the dead air between chunks and total speaking time. Same host, load 15 to 25, 5 repeats of 6 replies, old sentence-only splitting against the clause cut, two rounds:

| Reply | First audio p50, before to after | Dead air between chunks, before to after (mean, worst) | Total speaking p50, before to after |
|---|---|---|---|
| "That arrives in a later version, so for now I can open apps and change the volume." | 2987 to 1137 ms (round 2) | 0 to 0 ms | 8.58 to 7.17 s |
| "Sure, I can do that, but first I need to know which window you mean." | 2066 to 872 ms | 0 to 0 ms (round 1: 0 to 132 ms mean, 661 ms worst) | 6.42 to 5.48 s |
| "Done. I opened Calculator and set the volume to forty percent for you." | 476 to 468 ms | 1361 to 1236 ms (worst 1468 to 1286) | 6.97 to 6.80 s |
| All 6 replies | 1466 to 883 ms | 681 to 309 ms (worst 1468 to 1286) | 6.69 to 6.13 s |

So the clause cut starts speech 1 to 2 s sooner, adds no dead air worth the name (at most 0.66 s once, in one of four runs) and never lengthens the total. The one standing gap, about 1.3 s in "Done. I opened Calculator ...", is the second sentence taking longer to make than the first takes to say; it is the same with sentence-only splitting (M1 behaviour) and is not caused by the cut. A fix would need the next sentence synthesised while the first one is made (a deeper change in `speaker.py`) and is left as a follow-up. Replies with no clause mark in their first six words are a single chunk, and cannot start faster than the model allows: **the 400 ms target is not met** (about 1.25 s p50 for them here; Part A measured 600 to 660 ms on a quiet machine). It would need a smaller or faster model, which this task may not add.
