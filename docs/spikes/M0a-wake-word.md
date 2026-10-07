# M0a — Can "Jarvis" as the first word be detected accurately on-device?

**Hypothesis:** at least one candidate achieves ≤ 1 false accept per 8 h of normal room audio and ≤ 5% false rejects on the owner's voice, at ≤ 3% of one CPU core idle. The first-word rule (≥ 400 ms silence before plus the STT first-word gate) removes mid-sentence triggers (FR-ACT-04/05, ADR-0007).
**FRS refs:** FR-ACT-01…07, FR-ACT-15, §7.1, ADR-0007, FRS §12.1 risk 1.
**Candidates:**
1. openWakeWord stock "hey_jarvis" model, scored on a plain "Jarvis".
2. Picovoice Porcupine built-in "jarvis" (free personal AccessKey; licence noted).
3. Silero VAD plus a small whisper on each speech onset, checking the first word only (no wake model).
**Method:**
1. Owner records about 15 min: 50 × "Jarvis, <command>" at varying speed and distance; 20 × "Jarvis" alone; 30 sentences with "Jarvis" mid-sentence; 10 min of normal talk, typing and a meeting playing. All synthetic or self-recorded only (policy §2).
2. Add 1 h of public-domain speech or podcast audio for the false-accept rate.
3. Measure FR %, FA/h, detection latency and CPU % per candidate, with and without the first-word gate.
**Pass bar:** FA ≤ 1 per 8 h, FR ≤ 5%, mid-sentence false triggers ≤ 1 per 100 sentences after gating, idle CPU ≤ 3% of one core.
**Time-box:** 8 h (recording time excluded).

## Result (2026-10-07): synthetic voices

**What changed from the method:** the owner asked me to run this without recordings, so the evaluation set is **synthetic speech**: Piper TTS with 906 voices from 3 voice packs (904-speaker LibriTTS-R, plus en_GB Alan and en_US Lessac), speed 0.8–1.3×, and clean, pink, brown or white noise at 20, 10 or 5 dB SNR. Porcupine was not evaluated (it needs a Picovoice account key). Utterance segmentation is idealised (one clip = one utterance); real VAD is M1 work.

Set (`spikes/M0a-wake-word/generate.py`): 300 "Jarvis, <command>" · 100 "Jarvis" alone · 200 mid-sentence "Jarvis" · 200 sound-alikes ("Travis, …", "Service, …", "Harvest, …") · **60.1 min** of negative speech (602 utterances). Evaluator: `spikes/M0a-wake-word/evaluate.py`, with every stage cached.

| Candidate (best setting) | "Jarvis, …" detected | "Jarvis" alone | Mid-sentence fires | Sound-alike fires | False accepts |
|---|---|---|---|---|---|
| A: openWakeWord stock `hey_jarvis`, threshold 0.5 | 45.7% | 50.0% | 8.5% | 0.0% | 1 in 60 min |
| A: same, threshold 0.05 | 89.0% | 93.0% | 47.5% | 25.5% | 118 in 60 min |
| B: Whisper `tiny.en` first-word gate alone | 91.7% | 76.0% | 0.0% | 0.0% | 0 |
| B: + "Jarvis" as the initial prompt (FR-STT-03) | 92.0% | 90.0% | 0.0% | 0.5% | 0 |
| C: oww ≥ 0.005 → `tiny.en`+prompt gate | 90.7% | 90.0% | 0.0% | 0.5% | 0 |
| **D: C + fuzzy first word (≤ 2 edits from "jarvis", real words excluded)** | **94.3%** | **95.0%** | **0.0%** | **0.5%** | **0** |

**Cost:**
- openWakeWord always on: **2.90% of one core**.
- Whisper `tiny.en` gate: about 0.7 s wall per utterance (4 threads), run only on triggers. At oww ≥ 0.005 that's about 256 triggers per hour of *continuous* speech, and none in silence.

**Against the pass bar:**

| Bar | Result | |
|---|---|---|
| FA ≤ 1 per 8 h | 0 in 60 min | ⚠️ consistent, but 1 h can't prove a 1-per-8-h rate; needs ≥ 8 h of negatives |
| FR ≤ 5% | 5.7% commands, 5.0% "Jarvis" alone (D) | ⚠️ at the bar, on synthetic voices |
| Mid-sentence ≤ 1 per 100 | 0 / 200 | ✅ |
| Idle CPU ≤ 3% of one core | 2.90% (detector) | ✅, marginally |

**Caveats, so these numbers aren't over-trusted:**
1. Synthetic voices: real voices (including Indian-English accents) may score better or worse.
2. D's excluded real words were partly chosen from misses on this same set, so its recall is optimistic until checked on held-out data.
3. The stock model is trained on "hey jarvis", not "Jarvis". Its recall on a plain "Jarvis" is the weak link (89% at 0.05).
4. The negative speech is one hour of TTS (FRS sentences plus casual lines), not real rooms, TV or meetings.

## Decision

**GO on the architecture; PIVOT on the model.**

The FRS design (ADR-0007), a cheap always-on detector plus an STT first-word gate, works:
- 0 false accepts in an hour;
- 0 of 200 mid-sentence triggers;
- 1 of 200 sound-alikes;
- the detector stays within the CPU budget.

Recall sits right at the bar and depends on three things, which become M1 tasks:
1. **Train a custom single-word "Jarvis" openWakeWord model.** This is the biggest recall lever; it replaces stock `hey_jarvis`.
2. **Keep the gate:**
   - Whisper with "Jarvis" as its initial prompt (FR-STT-03);
   - fuzzy first-word matching against a maintained real-word exclusion list;
   - a larger STT model or Groq for the gate when online, since the gate only runs on triggers.
3. **Validate on real speech before calling the bar met:**
   - the owner's 15-minute set (`record.py` is ready);
   - at least 8 h of real negative audio;
   - the setup wizard's calibration step (FR-ACT-15) tunes thresholds per user.
