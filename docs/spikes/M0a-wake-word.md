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

## Result

_Pending._

## Decision

_Pending._
