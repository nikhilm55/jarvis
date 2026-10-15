"""Stage 3 — augment: dry clips -> noisy, reverberant, level-varied clips; plus real-speech and noise negatives.

  uv run --no-project --python 3.11 --with numpy==2.4.6 --with soundfile==0.13.1 python tools/wakeword/augment.py

Reads data/synth (generate.py), data/librispeech and data/noise (fetch.py); writes data/aug/<split>/<id>.wav
and data/aug/manifest.csv. Every random choice is seeded from the clip id, so a re-run is identical.
Per synthetic clip: with p=0.35 a stretch of other speech is put before a positive (so "Jarvis" is also heard
after talk), a synthetic room impulse response with p=0.45 (RT60 0.2-0.8 s), background noise with p=0.8 (DEMAND
recordings or white/pink/brown, SNR 3-30 dB), a band limit with p=0.15, then a random peak level.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import multiprocessing as mp
import os
import sys
import time
import wave
from pathlib import Path

import dsp
import numpy as np
from common import DATA, RATE, write_json, write_wav

SYNTH = DATA / "synth"
AUG = DATA / "aug"
NOISE = DATA / "noise"
LIBRI = DATA / "librispeech"
REAL_CHUNK_S = 8.0
VAL_ROOMS = {"OMEETING", "DLIVING"}  # of OOFFICE, OMEETING, DKITCHEN, DLIVING, PCAFETER
NOISE_ONLY = {"train": 1500, "val": 200}  # DEMAND-only negatives per split (+10% coloured noise)


def rng_for(name: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(name.encode()).hexdigest()[:8], 16))


def noise_files(split: str) -> list[Path]:
    """DEMAND recordings of the training rooms, or of the validation rooms (whole rooms are held out).

    The first model split by channel (1-12 train, 13-16 val), so validation shared its five rooms with training."""
    files = sorted(NOISE.rglob("ch*.wav"))
    return [f for f in files if (f.parent.name in VAL_ROOMS) == (split == "val")]


def noise_segment(files: list[Path], n: int, rng: np.random.Generator) -> np.ndarray:
    path = files[int(rng.integers(len(files)))]
    with wave.open(str(path), "rb") as handle:
        total = handle.getnframes()
        handle.setpos(int(rng.integers(max(1, total - n))))
        raw = handle.readframes(n)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def bandlimit(audio: np.ndarray, cutoff_hz: float) -> np.ndarray:
    spectrum = np.fft.rfft(audio)
    spectrum[int(cutoff_hz / (RATE / 2) * len(spectrum)) :] = 0
    return np.fft.irfft(spectrum, len(audio)).astype(np.float32)


def degrade(
    audio: np.ndarray, split: str, rng: np.random.Generator, *, rir_p: float, noise_p: float
) -> tuple[np.ndarray, dict[str, object]]:
    info: dict[str, object] = {}
    if rng.random() < rir_p:
        rt60 = float(rng.uniform(0.2, 0.8))
        audio = dsp.apply_rir(audio, dsp.synthetic_rir(rt60, rng))
        info["rt60"] = round(rt60, 2)
    if rng.random() < noise_p:
        snr = float(rng.uniform(3, 30))
        if rng.random() < 0.5:
            bed = noise_segment(noise_files(split), len(audio), rng)
            info["noise"] = "demand"
        else:
            kind = str(rng.choice(["white", "pink", "brown"], p=[0.2, 0.45, 0.35]))
            bed = dsp.colored_noise(kind, len(audio), rng)
            info["noise"] = kind
        audio = dsp.mix_at_snr(audio, bed, snr)
        info["snr_db"] = round(snr, 1)
    if rng.random() < 0.15:
        cutoff = float(rng.uniform(3500, 7000))
        audio = bandlimit(audio, cutoff)
        info["lowpass_hz"] = int(cutoff)
    peak = 0.9 if rng.random() < 0.3 else float(rng.uniform(0.1, 0.95))
    info["peak"] = round(peak, 2)
    return dsp.set_peak(audio, peak), info


def process(job: dict[str, str]) -> dict[str, object] | None:
    split, kind, name = job["split"], job["kind"], job["id"]
    rng = rng_for(name)
    word_end: float | str = ""
    if job["source"] == "synth":
        audio = _load(SYNTH / split / kind / f"{name}.wav")
        if kind == "pos":
            word_end = float(job["word_end_s"])
            if rng.random() < 0.35:
                other = _load(Path(job["context"]))
                length = int(rng.uniform(1.0, 3.0) * RATE)
                start = int(rng.integers(max(1, len(other) - length)))
                audio = np.concatenate([other[start : start + length], audio])
                word_end = float(word_end) + min(length, len(other)) / RATE
        audio, info = degrade(audio, split, rng, rir_p=0.45, noise_p=0.8)
    elif job["source"] == "real":
        audio = _load_flac(Path(job["path"]), int(job["start"]), int(job["stop"]))
        audio, info = degrade(audio, split, rng, rir_p=0.2, noise_p=0.5)
    else:  # noise-only
        n = int(rng.uniform(2.0, 5.0) * RATE)
        if job["kind"] == "noise" and rng.random() < 0.9:
            audio = noise_segment(noise_files(split), n, rng)
            info = {"noise": "demand"}
        else:
            audio = dsp.colored_noise(str(rng.choice(["white", "pink", "brown"])), n, rng)
            info = {"noise": "colored"}
        audio = dsp.set_peak(audio * float(rng.uniform(0.02, 1.0)), float(rng.uniform(0.02, 0.8)))
    out = AUG / split / f"{name}.wav"
    write_wav(out, audio)
    return {
        "id": name,
        "split": split,
        "kind": kind,
        "word_end_s": round(word_end, 3) if word_end != "" else "",
        "seconds": round(len(audio) / RATE, 2),
        "voice": job.get("voice", ""),
        "speaker": job.get("speaker", ""),
        "text": job.get("text", ""),
        "params": " ".join(f"{k}={v}" for k, v in info.items()),
    }


def _load(path: Path) -> np.ndarray:
    from common import read_wav

    return read_wav(path)


def _load_flac(path: Path, start: int, stop: int) -> np.ndarray:
    import soundfile

    audio, rate = soundfile.read(str(path), dtype="float32", start=start, stop=stop)
    if rate != RATE:
        raise ValueError(f"{path}: {rate} Hz")
    return np.asarray(audio, dtype=np.float32)


def plan() -> list[dict[str, str]]:
    with (SYNTH / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        synth = list(csv.DictReader(handle))
    jobs: list[dict[str, str]] = []
    contexts = {
        s: [r for r in synth if r["split"] == s and r["kind"] != "pos"] for s in ("train", "val")
    }
    for r in synth:
        job = {**r, "source": "synth"}
        if r["kind"] == "pos":
            pool = contexts[r["split"]]
            other = pool[int(rng_for(r["id"] + "ctx").integers(len(pool)))]
            job["context"] = str(SYNTH / other["split"] / other["kind"] / f"{other['id']}.wav")
        jobs.append(job)
    import soundfile

    speakers = sorted({p.parts[-3] for p in LIBRI.rglob("*.flac")})
    val_speakers = set(speakers[::5])
    for path in sorted(LIBRI.rglob("*.flac")):
        split = "val" if path.parts[-3] in val_speakers else "train"
        frames = soundfile.info(str(path)).frames
        step = int(REAL_CHUNK_S * RATE)
        for i, start in enumerate(range(0, frames, step)):
            if frames - start >= RATE:  # drop a trailing stub under 1 s
                jobs.append(
                    {"id": f"{split}-real-{path.stem}-{i}", "split": split, "kind": "real", "source": "real",
                     "path": str(path), "start": str(start), "stop": str(min(frames, start + step)), "speaker": path.parts[-3]}
                )  # fmt: skip
    for split, n in NOISE_ONLY.items():
        for i in range(n):
            jobs.append(
                {"id": f"{split}-noise-{i:05d}", "split": split, "kind": "noise", "source": "noise"}
            )
        for i in range(n // 10):
            jobs.append(
                {
                    "id": f"{split}-noisec-{i:05d}",
                    "split": split,
                    "kind": "noisec",
                    "source": "noise",
                }
            )
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()
    jobs = plan()
    print(f"{len(jobs)} clips to write; {args.workers} workers", flush=True)
    rows: list[dict[str, object]] = []
    start = time.time()
    with mp.get_context("spawn").Pool(args.workers) as pool:
        for n, row in enumerate(pool.imap_unordered(process, jobs, chunksize=16), 1):
            if row:
                rows.append(row)
            if n % 1000 == 0:
                print(f"  {n}/{len(jobs)}  {time.time() - start:.0f}s", flush=True)
    rows.sort(key=lambda r: str(r["id"]))
    with (AUG / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    hours = {
        s: sum(float(str(r["seconds"])) for r in rows if r["split"] == s) / 3600
        for s in ("train", "val")
    }
    write_json(AUG / "summary.json", {"clips": len(rows), "hours": hours})
    print(f"done: {len(rows)} clips, hours {hours}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
