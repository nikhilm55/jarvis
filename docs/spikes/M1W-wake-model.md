# M1W — a custom single-word "Jarvis" wake model

**Question:** can a model trained on the single word "Jarvis" replace the stock `hey_jarvis` and meet the FRS bar (FR-ACT-15: at most 1 false accept per 8 h, false rejects ≤ 5 %), with every input's licence recorded?
**Context:** M0a found recall at the bar only with a very low threshold plus the Whisper gate (table D, 94.3 %); the stock model is the wrong phrase and its CC BY-NC-SA 4.0 licence forbids shipping it (OQ-004, ADR-0010).
**Rulings:** R71–R77 (dev-only pipeline, synthetic positives with the M0a speakers held out, licences decide, CPU only, `--model` in the evaluator, the model never committed, a guard in `WakeDetector`).
**Code:** `tools/wakeword/` (pipeline and README), `spikes/M0a-wake-word/evaluate.py --model`, the guard in `src/jarvis/wake/detector.py`.
**Merge order:** #143 (guard) and #144 (`evaluate.py --model`) first; then the stack #145 → #146 → #147 → #148 → #149 → #150 → #151.

## Verdict: CONDITIONAL GO — proceed to real-voice and real-negative validation; FR-ACT-15 is NOT demonstrated

The first model is a good detector on synthetic speech, and it is worth building on. It does not show that Jarvis meets the FRS bar, and nothing below should be read as "met":

- **Recall.** E + gate detects 286 of 300 "Jarvis, …" clips (95.3 %, Wilson 95 % interval [92.3, 97.2]). Table D, with the stock model, detects 283 of 300 (94.3 %, [91.1, 96.4]). The difference is **3 clips and is not significant**; the intervals overlap almost completely. The gate, not the model, limits recall in both.
- **False rejects (bar ≤ 5 %).** On "Jarvis, …" the false-reject rate is 4.7 % (14/300; interval [2.8, 7.7]), and on the bare word 6.0 % (6/100; [2.8, 12.5]). Both intervals contain 5 %, so **both are undecided against the bar**; the bare word is the weaker of the two.
- **False accepts (bar ≤ 1 per 8 h = 0.125 per hour).** 0 false accepts in 60.1 minutes bounds the rate below **about 3 per hour** (rule of three, 95 %). Certifying 0.125 per hour with zero events needs about **24 h** of negatives (3 / 0.125), not 8 h. The 60-minute set is synthetic TTS of FRS sentences and cannot show the rate in a room.
- **The model alone is not a wake word.** On validation it reaches 79.6 % recall at the false-accept target (≤ 0.125 per hour on the validation negatives), and at the chosen 99 %-recall threshold it still gives 4.9 false accepts per hour. On the 60-minute M0a negatives it fires 4 times, and the gate rejected all 4. So the system depends on the gate, and that dependence rests on **4 events**.
- **The gate was tuned on M0a.** D's `REAL_WORDS` list and the 2-edit rule were chosen from misses on the same set (`evaluate.py`; M0a caveat 2). Every gated number here (C, D, E + gate) is therefore not held out; only the alone numbers are, and those have the overlaps listed next.
- **The hold-out is speaker-level only for this model.** See "What the hold-out does and does not cover".

## Method

| Stage (`tools/wakeword/`) | What | Cost |
|---|---|---|
| fetch | pinned downloads, byte ledger, refuses past 2 GB | 1,169 MB, about 13 min |
| generate | Piper: 4,500 "Jarvis" / "Jarvis, <command>" clips; 2,800 sound-alike clips; 5,600 sentences | 12,900 clips, 12.8 h, 18 min on 12 cores |
| augment | reverb (45 %), noise (80 %, SNR 3–30 dB, DEMAND or coloured), band limit, level, prior speech; plus real speech and noise-only clips | 18,318 clips, 21 h, under 1 min |
| features | the detector's own feature path, 96-d embedding per 80 ms frame | 12 min |
| train | 16×96 MLP with layer norm (openWakeWord's "dnn" shape), dropout 0.2, 12 epochs | 4 min |
| export | ONNX, checked against torch (max diff 1.8e-7) | under 1 min |

- **Labels:** a positive clip's windows ending from 80 ms before to 400 ms after the end of "Jarvis" are positive; windows ending well before the word are negative; the rest of a positive clip is ignored. Every window of a negative clip is negative. Sound-alikes weigh double; negatives still scored above 0.2 after an epoch get their weight doubled.
- **Split:** train 15,986 clips (18.0 h), validation 2,332 clips (2.7 h, of which 2.2 h negatives). Validation speakers are 12 % of the speaker pairs plus one whole voice (`joe`); validation real speech is 8 LibriSpeech speakers.
- **Operating point:** the checkpoint and the threshold (0.7839) come from validation data: the epoch with the fewest validation false accepts at the threshold that still detects 99 % of validation positives. No decision was made on M0a numbers. One list change followed validation evidence before M0a was scored: the near-homophone spellings (Jervis, Darvis, Jarvik, …) were removed from the negatives after the first training run. But the validation set overlaps training in text and noise rooms (below), so the threshold and the validation false-accept rates are optimistic by an unknown amount.

## What the hold-out does and does not cover

R72 asked to hold out every (voice, speaker) pair in the M0a manifest. That holds: 659 roster pairs, 0 in M0a. The first sensor only compared whole strings, though, and a review found overlaps it could not see. `check_holdout.py` now compares composite texts, command tails and sound-alike words, and checks that validation text is not in training. Run on **the first model's data**:

```
$ WAKEWORD_DATA=tools/wakeword/data python tools/wakeword/check_holdout.py
roster: 659 (voice, speaker) pairs, 0 also in M0a
generated clips: 659 (voice, speaker) pairs, 0 also in M0a
augmented clips: 659 (voice, speaker) pairs, 0 also in M0a
M0a: 370 pairs, 497 distinct texts; 12900 generated clips
generated clips whose full text is an M0a clip text: 123
generated clips whose command is an M0a command: 192  ['open settings', 'stop', 'take a screenshot']
validation clips whose text is also in training: 926
WARNING word-level: 581 sound-alike clips start with an M0a sound-alike word ['davis', 'elvis', 'garvey', 'harvest', 'jars', 'nervous', 'service', 'travis']
HOLD-OUT VIOLATED: 123 clips with M0a composite texts; 192 clips with M0a command tails; 926 clips with validation texts also in training
```

What that means for the first model's numbers:

1. **Texts and commands.** 192 training clips use three commands that M0a also uses, and 123 of them say an M0a clip text word for word ("Jarvis, open Settings"). The speakers differ, so this is not a speaker leak, but the model has heard those phrases. The sound-alike list was seeded from M0a's own confusable list: 8 of M0a's 8 sound-alike words ("Jars of" counted as "Jars") were in training.
2. **Sound-alikes.** The 4.0 % M0a sound-alike rate was measured on words the model trained on, so unseen sound-alikes are likely **worse**, not better.
3. **Validation.** The validation sentences (926 clips) also occur in training, the commands are shared, and the validation noise is other microphones of the same five DEMAND rooms. The validation threshold, the 79.6 % and the 4.9 per hour are optimistic.
4. **Next run only.** `texts.py` now drops the 3 M0a commands and the 8 M0a sound-alike words (keeping the brief's Marvin, Paris, Harris); validation has its own commands, casual lines and the sentences of every fifth LibriSpeech speaker, and `generate.py` asserts that the splits say nothing in common; the noise rooms are split by room (OMEETING and DLIVING are validation only). A dry plan of the full next run through the new sensor gives 0 composite overlaps, 0 command overlaps, 0 validation texts in training and 0 M0a sound-alike words. **The first model's data and numbers were not regenerated.**

## Result on the M0a held-out set (1,402 clips, 60.1 min of negatives)

Model: `tools/wakeword/data/model/jarvis.onnx`, 857,069 bytes, SHA-256 `7bd6b949755b15c7504016f5f0f55aea8630f76db4fd8ee65165eea73608635e` (not committed, R76). Intervals are Wilson 95 %.

| Candidate | Detects "Jarvis, …" (n = 300) | "Jarvis" alone (n = 100) | Sound-alikes (n = 200) | False accepts in 60.1 min |
|---|---|---|---|---|
| A: stock `hey_jarvis`, 0.5 | 45.7 % [40.1, 51.3] | 50.0 % | 0.0 % | 1 |
| A: stock, 0.05 | 89.0 % [85.0, 92.1] | 93.0 % | 25.5 % | 118 |
| C: stock ≥ 0.005 + gate | 90.7 % [86.8, 93.5] | 90.0 % | 0.5 % | 0 |
| D: C + fuzzy first word (gate tuned on M0a) | 94.3 % [91.1, 96.4] | 95.0 % [88.8, 97.8] | 0.5 % [0.1, 2.8] | 0 |
| E alone, 0.78 | 99.0 % [97.1, 99.7] | 99.0 % [94.6, 99.8] | 4.0 % [2.0, 7.7] | 4 |
| E alone, 0.5 | 99.7 % | 99.0 % | 5.0 % | 6 |
| E alone, 0.9 | 98.7 % | 99.0 % | 2.0 % | 4 |
| **E + gate, 0.78** | **95.3 % [92.3, 97.2]** | **94.0 % [87.5, 97.2]** | **0.0 % [0.0, 1.9]** | **0** (bound: < 3 per hour) |
| E + gate, 0.005 | 96.0 % | 95.0 % | 1.0 % | 0 |
| E + gate, 0.5 | 95.7 % | 94.0 % | 0.5 % | 0 |

Mid-sentence "Jarvis" fires 74.0 % of the time for E alone (148/200) and 0 % behind the gate; the first-word rule is the gate's job. The full threshold grid (0.005 … 0.9) is what `evaluate.py --model` prints. Reading it plainly: the new model detects 99.0 % of commands where the stock model detects 89.0 % at a threshold with 118 false accepts, which is a real gain for the detector; the gated 95.3 % versus 94.3 % is not a measured gain.

**The four false accepts of E alone** (0.78) are two clips with code or symbol text that the TTS spells out (`catalog.yaml …`, 0.998; `B- D: final response {status: success …}`, 0.995) and **two ordinary sentences**: "Status: APPROVED by Nikhil on 2026-10-06." (0.991) and "Speak: "I've written it in Rahul Sharma's chat."" (0.904). So the model also fires on plain speech, which matches its 4.9 false accepts per hour on validation.

### The product's own detector scores the model (requirement 6)

`tools/wakeword/product_check.py` builds the product's `WakeDetector` around the new classifier (`Backends`, so the streaming path, warm-up, replay and the R77 guard are the shipped code) and scores all M0a clips:

```
$ uv run python tools/wakeword/product_check.py --model .../jarvis.onnx --scores .../oww-custom-7bd6b949755b.json --all --threshold 0.78
product vs openWakeWord: 1402 clips, max abs diff 0.00e+00, mean 0.00e+00
product WakeDetector fires at >= 0.78: jarvis_command 297/300, jarvis_alone 99/100, jarvis_mid_sentence 148/200, confusable 8/200, negative_speech 4/602
PRODUCT PARITY PASS
```

Same scores as openWakeWord's own `predict_clip`, so `evaluate.py`'s table is what the product will see. The R77 guard accepts this model (16 features; limit 39).

## Inputs and licences (R73)

**Downloaded:** `fetch.py` 1,169 MB, plus about 230 MB of Python wheels for the throwaway env (torch 2.9.1 CPU 184 MB, onnx 18 MB, small ones), plus **528 MB downloaded again by mistake during the review fixes** (`fetch.py` run in a scratch worktree with no data directory; the 12 voice files were fetched a second time and deleted). Total about **1,930 MB, under the 2,000 MB line but close**; the earlier statement that the total stayed under even if the uv cache growth were counted no longer holds. No further downloads were made beyond a few model cards and web pages.

### Piper voices (MODEL_CARD URLs are at revision `c10ece1aade47bb51c153c893d14e5bf8e5b7117` of `huggingface.co/rhasspy/piper-voices`, path `en/<locale>/<voice>/medium/MODEL_CARD`)

| Voice (use) | Dataset licence, as quoted | Source check | Lineage, as quoted | Verdict |
|---|---|---|---|---|
| `en_US-libritts_r-medium`, 536 of 904 speakers (train and val) | card: "License: CC BY 4.0" | **verified**: openslr.org/141 "License: CC BY 4.0" | card: "Fine-tuned from English lessac medium on train-clean-360." | data clean; **lessac lineage** |
| `en_GB-vctk-medium`, 109 speakers | card: "License: https://creativecommons.org/licenses/by/4.0/" | **unverified at source**: the Edinburgh DataShare page (datashare.ed.ac.uk/handle/10283/3443) lists `license_text.txt` but its text did not load | card: "Finetuned from U.S. English lessac voice (medium quality)." | data licence from the card only; **lessac lineage** |
| `en_GB-aru-medium`, 12 speakers | card: "License: https://creativecommons.org/licenses/by/4.0/" | **contradicted**: the Liverpool data catalogue (datacat.liverpool.ac.uk/681) lists the audio archive as "Creative Commons: Attribution 3.0" (only the read-me is 4.0); the card's source URL now returns 404 | card: "Finetuned from U.S. English lessac voice (medium quality)." | **not CC BY 4.0 as the card says; drop in the next run** |
| `en_US-ljspeech-medium` (train) | card: "License: public domain" | **verified**: keithito.com/LJ-Speech-Dataset "License Public Domain … There are no restrictions on its use" | card: "Trained from scratch for 1000 epochs on medium quality settings using the LJ Speech dataset." | clean; **the only voice here without lessac lineage** (single speaker) |
| `en_US-joe-medium` (val only) | card: "License: CC0" | **unverified at source** (github.com/OHF-Voice/voice-datasets not read) | card: "Finetuned from U.S. English lessac voice (medium quality)." | **lessac lineage**, so it is not a lessac-free fallback |
| `en_US-lessac-medium` (not used for training; an M0a voice) | card: "License: https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html" | licence text read through a web fetch (the raw page did not reproduce with curl; **confirm it yourself**) | card: "Trained from scratch." | see below |

The Lessac (Blizzard 2013) licence, clause 1.1, as returned by the fetch: "Research Purposes" means "only those purposes associated with research and exploration … and for the avoidance of doubt excludes loading, executing, storing, transmitting, displaying, copying, reverse engineering, developing, adapting, amending or otherwise using the Materials for any commercial purpose, including the development, marketing, commercialisation, sale or licencing of voice synthesis or speech recognition products or services including, without limitation, voice synthesis products or services, speech recognition products and services, and other speech technology products and services." Clause 3.2 grants the licence "exclusively for Research Purposes only". Whether a speech-technology product trained on audio from a *fine-tuned descendant* of a model trained on those Materials is covered is a legal question I cannot answer; the clause is broad enough that the owner should decide before shipping (OQ-009 in this PR).

### Other inputs

| Input | Used for | Size | Licence, as quoted | Source check |
|---|---|---|---|---|
| openWakeWord `melspectrogram.onnx`, `embedding_model.onnx` v0.5.1 | frozen feature front end (also the product's) | 2.4 MB | repository: Apache-2.0; README: the backbone "is provided by Google … under an Apache-2.0 license", but "All of the included pre-trained models are licensed under … CC BY-NC-SA 4.0" | **unverified for these two release files** (the README's blanket sentence may cover them; the product already downloads them; in OQ-009) |
| LibriSpeech dev-clean | real-speech negatives; transcripts as TTS sentences | 338 MB | "License: CC BY 4.0" | **verified**: openslr.org/12 |
| DEMAND 16 kHz: OOFFICE, OMEETING, DKITCHEN, DLIVING, PCAFETER | background noise | 469 MB | Zenodo record 1227121 licence `cc-by-4.0` | **verified**: Zenodo API |
| Room impulse responses | reverb | none | synthetic (`dsp.py`) | n/a |

Tools (not shipped): `piper-tts` 1.8.0 and espeak-ng (GPL-3.0, from memory, **unverified this round**), `onnxruntime` 1.30.0, `numpy`, `scipy`, `soundfile`, `torch` 2.9.1, `onnx` 1.19.1, `openwakeword` 0.6.0 (evaluator only).

### Can the model ship?

**Not decided.** CC BY inputs (LibriTTS-R, LibriSpeech, DEMAND, and VCTK per its card) need attribution in the third-party notices. The open points are the Lessac lineage of four of the five voices and the two openWakeWord front-end files. OQ-009 asks the owner. Until it is answered the file should be treated as unshippable.

## Next run (all of it needs the owner's go-ahead; no retraining was done in this round)

Owner's choices:
1. **(a)** Accept the lessac lineage as outside the clause, and keep the four lineage voices.
2. **(b)** Train only on voices without lessac lineage. Today that is `ljspeech` alone (one speaker); any larger roster needs voices the owner approves, whose lineage and licence must be quoted as above.
3. **(c)** Have the owner (or counsel) check the Lessac terms, and the openWakeWord front-end files, first.

Then, whichever is chosen:
- the fixed lists and splits above (the sensor must exit 0 before training: `check_holdout.py`);
- **real recordings**: the owner's 15-minute set (`record.py`), in Indian-English and other accents;
- **about 24 h of real negative audio** (meetings, TV, rooms) to bound false accepts at 0.125 per hour;
- **a second training seed**, to show how stable the 99 %-recall threshold and the false-accept rates are;
- **gate rules derived from non-M0a data** (the exclusion list and the edit distance), so the gated numbers are held out;
- results reported with intervals, and a recall comparison stated as significant only when the intervals separate.

## Reproduce

`tools/wakeword/README.md`: six stages, one command each, pinned versions, every stage cached to `tools/wakeword/data/`. Compute used for the first model: about 2 h wall-clock on 14 cores (about 14 core-hours including a repeated generate/augment/features run after the sound-alike list was fixed); the cap was 1 day.
