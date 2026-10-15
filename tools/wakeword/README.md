# tools/wakeword — train a single-word "Jarvis" wake model

Dev-only pipeline (owner rulings R71–R77). It is never imported by `src/` and never shipped. It produces an
openWakeWord-format ONNX classifier to replace the stock `hey_jarvis_v0.1` (wrong phrase; CC BY-NC-SA 4.0, so not
shippable; OQ-004, ADR-0010). **The model file is never committed** (R76): the owner publishes it, and only then is it
registered in `jarvis.models`. Results and the licence audit: `docs/spikes/M1W-wake-model.md`.

CPU only. Every stage reads the previous stage's files from `tools/wakeword/data/` (gitignored; override with
`WAKEWORD_DATA`) and writes its own, so each can be re-run alone. Commands run from the repo root, in a throwaway env
(`uv run --no-project`), so nothing is added to `pyproject.toml`.

| # | Stage | Command (after `uv run --no-project --python 3.11`) | Output |
|---|---|---|---|
| 1 | fetch | `python tools/wakeword/fetch.py` | `data/downloads`, `data/librispeech`, `data/noise`, `data/ledger.json` |
| 2 | generate | `--with piper-tts==1.8.0 --with onnxruntime==1.30.0 --with scipy==1.17.1 --with numpy==2.4.6 python tools/wakeword/generate.py` | `data/synth/` dry clips + `manifest.csv` + `roster.json` |
| 3 | augment | `--with numpy==2.4.6 --with soundfile==0.13.1 python tools/wakeword/augment.py` | `data/aug/` clips + `manifest.csv` |
| 4 | features | `--with numpy==2.4.6 --with onnxruntime==1.30.0 python tools/wakeword/features.py` | `data/features/{train,val}.npz` |
| 5 | train | `--with numpy==2.4.6 --with torch==2.9.1 --extra-index-url https://download.pytorch.org/whl/cpu python tools/wakeword/train.py` | `data/model/classifier.pt`, `train.json` |
| 6 | export | `--with numpy==2.4.6 --with onnxruntime==1.30.0 --with onnx==1.19.1 --with torch==2.9.1 --extra-index-url https://download.pytorch.org/whl/cpu python tools/wakeword/export.py` | `data/model/jarvis.onnx`, `jarvis.json` (SHA-256, size, threshold) |

Then the checks:

```bash
# Hold-out proof (R72): exits 1 if a clip uses an M0a (voice, speaker) pair, says an M0a text or command, or has a
# validation text that also occurs in training; word-level overlap with M0a's sound-alike words is printed as a warning.
uv run --no-project --python 3.11 python tools/wakeword/check_holdout.py

# Candidate E on the M0a held-out set (R75): alone and behind table D's gate, same table shape as C/D.
M0A_DATA=<scratch copy of spikes/M0a-wake-word/data> uv run --no-project --python 3.11 \
  --with openwakeword==0.6.0 --with piper-tts==1.8.0 --with onnxruntime==1.30.0 \
  python spikes/M0a-wake-word/evaluate.py --model tools/wakeword/data/model/jarvis.onnx

# The product's WakeDetector scores the model and agrees with openWakeWord (run in the project env).
uv run python tools/wakeword/product_check.py --model tools/wakeword/data/model/jarvis.onnx --scores <scratch>/cache/oww-custom-<hash>.json
```

`python tools/wakeword/errors.py` (same env as train) lists the validation clips the model gets wrong, by kind and first word.

## What the stages do

1. **fetch** — stdlib only. Every input is pinned by SHA-256 (taken from the host's own checksum where it publishes
   one; Zenodo's md5 is checked too) in `pins.py`. `data/ledger.json` sums the bytes
   downloaded; the script refuses a download that would take the total past 2 GB (R73), which is a stop-and-ask line.
   `python fetch.py --list` prints each item's size, licence and URL.
2. **generate** — Piper (`piper-tts`) synthesises "Jarvis" (with `. , ! ?` variants), optionally followed by a short
   command, plus negatives: sound-alikes ("Travis, open Teams"; Davis, service, nervous, harvest, jars, Elvis,
   Marvin, Paris, Harris, …) and general sentences from LibriSpeech transcripts. Speaker roster: `speakers.py` removes
   every (voice, speaker) pair that appears in the M0a `manifest.csv` (R72), then splits the rest into train and val by
   a seeded hash of the pair; one whole voice (`joe`) is val-only. The end of the wake word is recorded in the
   manifest so training windows can be labelled exactly.
3. **augment** — per clip, seeded by its id: a stretch of other speech before the word (35 %), a synthetic room
   impulse response (45 %, RT60 0.2–0.8 s), background noise (80 %: DEMAND recordings or white/pink/brown, SNR 3–30 dB),
   a band limit (15 %) and a random level. It also adds negatives: real speech (LibriSpeech dev-clean, split by
   speaker) and noise-only clips.
4. **features** — the product's own feature path (`src/jarvis/wake/detector.py`) applied to whole clips: mel, 76-row
   windows at stride 8, one 96-d embedding per 80 ms frame, behind the 41 "primed" embeddings the detector starts with.
5. **train** — a 16×96 → 128 → 128 → 1 MLP with layer norm (the architecture of openWakeWord's custom-model "dnn").
   Positive windows end within −80…+400 ms of the word's end; every window of a negative clip is negative; sound-alikes
   weigh double and negatives still scored above 0.2 after an epoch get their weight doubled. Dropout 0.2. The kept epoch
   and the threshold come from the validation split only: the highest threshold that still detects 99 % of validation
   positives (the validation split is too short, 2.2 h of negatives, to certify 1 false accept per 8 h).
6. **export** — `torch.onnx.export` (opset 17), checked against torch and onnxruntime, with the SHA-256 and size
   recorded in `jarvis.json`.

## Deviations from the ruling, and why

- **openWakeWord's `train.py` is not used.** Its pipeline needs ~15 more packages (torchmetrics, speechbrain,
  audiomentations, acoustics, …) and its negative-feature set (ACAV100M, ≈16 GB) is far past the 2 GB line (R73). This
  pipeline reimplements the parts that matter — the same feature path (so training and the product agree by
  construction), the same classifier architecture and the same output format — with the openWakeWord models
  `melspectrogram.onnx` / `embedding_model.onnx` (v0.5.1, Apache-2.0) as the frozen front end.
- **`piper-sample-generator` is not used**; `piper-tts` is called directly (the same package the M0a set was made with).
- **Room impulse responses are synthetic** (exponentially decaying noise), not a measured set, to avoid another
  download and licence.

## Tests

`tests/test_wakeword_speakers.py`, `test_wakeword_holdout.py`, `test_wakeword_generate.py`, `test_wakeword_fetch.py` and
`test_wakeword_dsp.py` (noise, SNR, RIR helpers) run in
the normal suite.

## Status of the first model's data

The first model (card: `docs/spikes/M1W-wake-model.md`) was trained before the text and noise splits below existed, and
`check_holdout.py` run on its data exits 1 (M0a texts and commands in training, validation texts in training). The fixes
apply to the next run only: the M0a commands and sound-alike words are gone from `texts.py`, validation has its own
commands, casual lines and LibriSpeech speakers (`generate.py` asserts the splits share nothing), the noise rooms are
split by room (`augment.py`), `fetch.py` enforces the 2 GB budget on real bytes, and `check_holdout.py` must exit 0 before
a model is trained or evaluated.
