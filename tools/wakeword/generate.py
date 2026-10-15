"""Stage 2 — generate: synthesise dry (clean) clips with Piper, held-out speakers excluded.

  uv run --no-project --python 3.11 --with piper-tts==1.8.0 --with onnxruntime==1.30.0 \
      --with scipy==1.17.1 --with numpy==2.4.6 python tools/wakeword/generate.py [--scale 1.0]

Writes data/synth/<split>/<kind>/<id>.wav (16 kHz mono) and data/synth/manifest.csv.
Positives are "Jarvis" (+ punctuation variants), optionally followed by a short command; the end
of the wake word is recorded (`word_end_s`) so the training windows can be labelled exactly.
Negatives are sound-alikes ("Travis, open Teams") and general sentences. Resumable: a clip that
already exists is skipped. The speaker roster comes from speakers.py (M0a pairs held out).
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import random
import sys
import time
from dataclasses import asdict, dataclass

os.environ.setdefault("OMP_NUM_THREADS", "1")

from common import DATA, M0A, RATE, write_json, write_wav
from speakers import Speaker, assert_disjoint, build_roster, load_held_out
from texts import (
    CASUAL,
    COMMANDS,
    PUNCT,
    SOUND_ALIKES,
    librispeech_sentences,
    split_every,
    val_speaker_ids,
)

VOICES = {
    "en_US-libritts_r-medium": 0.40,  # weight when drawing a voice
    "en_GB-vctk-medium": 0.30,
    "en_GB-aru-medium": 0.10,
    "en_US-ljspeech-medium": 0.10,
    "en_US-joe-medium": 0.10,
}
VAL_VOICES = frozenset({"en_US-joe-medium"})  # a whole voice the model never trains on
COUNTS = {  # (split, kind) -> clips at --scale 1.0
    ("train", "pos"): 4000,
    ("val", "pos"): 500,
    ("train", "alike"): 2500,
    ("val", "alike"): 300,
    ("train", "speech"): 5000,
    ("val", "speech"): 600,
}
SYNTH = DATA / "synth"
VOICE_DIR = DATA / "downloads"


@dataclass(frozen=True)
class Job:
    id: str
    split: str
    kind: str
    voice: str
    speaker: str
    text: str
    command: str
    length_scale: float
    noise_scale: float
    noise_w: float
    lead_s: float
    gap_s: float


def build_roster_for_run() -> list[Speaker]:
    voices = {}
    for name in VOICES:
        cfg = VOICE_DIR / f"{name}.onnx.json"
        import json

        voices[name] = int(json.loads(cfg.read_text(encoding="utf-8"))["num_speakers"])
    held_out = load_held_out(M0A / "clips" / "manifest.csv")
    roster = build_roster(voices, held_out, val_voices=VAL_VOICES)
    assert_disjoint(roster, held_out)
    return roster


def text_pools(sentences: list[tuple[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Per split, the commands, casual lines and sentences it may use; the splits share none."""
    val_ids = val_speaker_ids(s for s, _ in sentences)
    commands, casual = split_every(COMMANDS, 5), split_every(CASUAL, 4)
    return {
        "train": {
            "commands": commands[0],
            "casual": casual[0],
            "sentences": [t for s, t in sentences if s not in val_ids],
        },
        "val": {
            "commands": commands[1],
            "casual": casual[1],
            "sentences": [t for s, t in sentences if s in val_ids],
        },
    }


def full_text(job: Job) -> str:
    return f"{job.text} {job.command}".lower().translate(str.maketrans("", "", ".,!?")).strip()


def says_something(job: Job) -> bool:
    """A sentence or a word plus a command (a bare wake or sound-alike word is shared by design)."""
    return job.kind == "speech" or bool(job.command)


def assert_text_disjoint(jobs: list[Job]) -> None:
    """Raise if a validation clip says something (sentence or word + command) a training clip says."""
    train = {full_text(j) for j in jobs if j.split == "train" and says_something(j)}
    shared = sorted({full_text(j) for j in jobs if j.split == "val" and says_something(j)} & train)
    if shared:
        raise ValueError(
            f"{len(shared)} validation texts also occur in training, e.g. {shared[0]!r}"
        )


def plan(
    roster: list[Speaker], scale: float, sentences: list[tuple[str, str]], seed: int = 7
) -> list[Job]:
    rng = random.Random(seed)
    pools = text_pools(sentences)
    if not pools["train"]["sentences"] or not pools["val"]["sentences"]:
        raise SystemExit("no LibriSpeech transcripts: run fetch.py first")
    by_split: dict[str, dict[str, list[Speaker]]] = {"train": {}, "val": {}}
    for sp in roster:
        by_split[sp.split].setdefault(sp.voice, []).append(sp)
    jobs: list[Job] = []
    for (split, kind), n in COUNTS.items():
        voices = by_split[split]
        names = list(voices)
        weights = [VOICES[v] for v in names]
        texts = pools[split]
        for i in range(round(n * scale)):
            sp = rng.choice(voices[rng.choices(names, weights)[0]])
            command = ""
            if kind == "pos":
                text = "Jarvis" + rng.choice(PUNCT)
                if rng.random() < 0.45:
                    command = rng.choice(texts["commands"])
            elif kind == "alike":
                text = rng.choice(SOUND_ALIKES) + rng.choice(PUNCT)
                if rng.random() < 0.6:
                    command = rng.choice(texts["commands"])
            else:
                text = rng.choice(texts["casual" if rng.random() < 0.15 else "sentences"])
            jobs.append(
                Job(
                    id=f"{split}-{kind}-{i:05d}",
                    split=split,
                    kind=kind,
                    voice=sp.voice,
                    speaker=sp.speaker,
                    text=text,
                    command=command,
                    length_scale=round(rng.uniform(0.8, 1.3), 2),
                    noise_scale=round(rng.uniform(0.5, 0.9), 2),
                    noise_w=round(rng.uniform(0.6, 1.0), 2),
                    lead_s=round(rng.uniform(0.5, 1.4), 2),
                    gap_s=round(rng.choice([0.05, 0.1, 0.2, 0.3, 0.5]), 2),
                )
            )
    assert_text_disjoint(jobs)
    return jobs


_voices: dict[str, object] = {}


def _init() -> None:
    import onnxruntime
    from piper import PiperVoice

    options = (
        onnxruntime.SessionOptions()
    )  # one thread per worker: 12 workers x 14 threads thrashes
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    for name in VOICES:
        voice = PiperVoice.load(str(VOICE_DIR / f"{name}.onnx"))
        voice.session = onnxruntime.InferenceSession(
            str(VOICE_DIR / f"{name}.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        _voices[name] = voice


def _synth(job: Job, text: str):  # type: ignore[no-untyped-def]
    import numpy as np
    from piper import SynthesisConfig
    from scipy.signal import resample_poly

    voice = _voices[job.voice]
    speaker = int(job.speaker) if job.speaker else None
    config = SynthesisConfig(
        speaker_id=speaker,
        length_scale=job.length_scale,
        noise_scale=job.noise_scale,
        noise_w_scale=job.noise_w,
    )
    chunks = [
        np.asarray(c.audio_float_array, dtype=np.float32) for c in voice.synthesize(text, config)
    ]  # type: ignore[attr-defined]
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    audio = resample_poly(audio, RATE, voice.config.sample_rate).astype(np.float32)  # type: ignore[attr-defined]
    peak = float(np.max(np.abs(audio))) or 1.0
    voiced = np.nonzero(np.abs(audio) > 0.03 * peak)[0]  # trim the TTS's own leading/trailing air
    if voiced.size:
        pad = int(0.03 * RATE)
        audio = audio[max(0, voiced[0] - pad) : voiced[-1] + pad]
    return audio


def run_job(job: Job) -> dict[str, object] | None:
    import numpy as np

    out = SYNTH / job.split / job.kind / f"{job.id}.wav"
    row: dict[str, object] = asdict(job)
    try:
        wake = _synth(job, job.text)
        parts = [np.zeros(int(job.lead_s * RATE), dtype=np.float32), wake]
        word_end = job.lead_s + len(wake) / RATE
        if job.command:
            parts += [np.zeros(int(job.gap_s * RATE), dtype=np.float32), _synth(job, job.command)]
        parts.append(np.zeros(int(0.5 * RATE), dtype=np.float32))
        clip = np.concatenate(parts)
        clip *= 0.9 / max(1e-6, float(np.max(np.abs(clip))))
        if not out.exists():
            write_wav(out, clip)
    except Exception as exc:  # one bad synthesis must not stop an hours-long job
        print(f"FAILED {job.id}: {exc!r}", file=sys.stderr, flush=True)
        return None
    row.update(
        word_end_s=round(word_end, 3) if job.kind == "pos" else "",
        seconds=round(len(clip) / RATE, 2),
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scale", type=float, default=1.0, help="multiply every clip count")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()
    roster = build_roster_for_run()
    write_json(SYNTH / "roster.json", [asdict(s) for s in roster])
    jobs = plan(roster, args.scale, librispeech_sentences(DATA / "librispeech"))
    print(
        f"{len(jobs)} clips from {len(roster)} (voice, speaker) pairs; {args.workers} workers",
        flush=True,
    )
    rows: list[dict[str, object]] = []
    start = time.time()
    with mp.get_context("spawn").Pool(args.workers, initializer=_init) as pool:
        for n, row in enumerate(pool.imap_unordered(run_job, jobs, chunksize=8), 1):
            if row:
                rows.append(row)
            if n % 250 == 0:
                print(f"  {n}/{len(jobs)}  {time.time() - start:.0f}s", flush=True)
    rows.sort(key=lambda r: str(r["id"]))
    with (SYNTH / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"done: {len(rows)} clips, {sum(float(str(r['seconds'])) for r in rows) / 3600:.2f} h",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
