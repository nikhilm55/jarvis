"""Stage 4 — features: openWakeWord embeddings of every augmented clip, exactly as the product computes them.

  uv run --no-project --python 3.11 --with numpy==2.4.6 --with onnxruntime==1.30.0 python tools/wakeword/features.py

The product (src/jarvis/wake/detector.py) feeds 80 ms frames through the melspectrogram model (mel/10+2), keeps the
newest 76 mel rows (stride 8 per frame) and embeds them: one 96-d embedding per frame. The classifier reads the newest
16 embeddings, and the buffer starts as 41 embeddings of seeded noise ("primed"). This stage reproduces that on whole
clips and stores, per clip, [primed 41 rows; one embedding per full 80 ms frame]. Output: data/features/<split>.npz.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import sys
import time

import numpy as np
from common import DATA, FRAME, RATE, read_wav

MEL_BINS, WINDOW, STRIDE, EMBED_DIM = 32, 76, 8, 96
PRIME_SAMPLES, PRIME_SEED = 64_000, 0
AUG = DATA / "aug"
OUT = DATA / "features"
_sessions: dict[str, object] = {}


def _init() -> None:
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    for name, file in (("mel", "melspectrogram.onnx"), ("embed", "embedding_model.onnx")):
        _sessions[name] = onnxruntime.InferenceSession(
            str(DATA / "downloads" / file), sess_options=options, providers=["CPUExecutionProvider"]
        )


def melspec(samples: np.ndarray) -> np.ndarray:
    """Mel rows of int16-scale float32 samples, with the product's /10 + 2."""
    session = _sessions["mel"]
    out = session.run(None, {session.get_inputs()[0].name: samples[None, :]})[0]  # type: ignore[attr-defined]
    return np.asarray(out, dtype=np.float32).reshape(-1, MEL_BINS) / 10 + 2


def embed(windows: np.ndarray) -> np.ndarray:
    session = _sessions["embed"]
    out = session.run(None, {session.get_inputs()[0].name: windows})[0]  # type: ignore[attr-defined]
    return np.asarray(out, dtype=np.float32).reshape(windows.shape[0], EMBED_DIM)


def primed() -> np.ndarray:
    """The detector's initial feature buffer: embeddings of 4 s of seeded noise."""
    noise = np.random.default_rng(PRIME_SEED).integers(-1000, 1000, PRIME_SAMPLES).astype(np.int16)
    spec = melspec(noise.astype(np.float32))
    windows = [
        spec[i : i + WINDOW] for i in range(0, spec.shape[0], STRIDE) if i + WINDOW <= spec.shape[0]
    ]
    return embed(np.expand_dims(np.array(windows), -1).astype(np.float32))


def clip_embeddings(audio: np.ndarray) -> np.ndarray:
    """One embedding per full 80 ms frame, as the streaming detector would produce them."""
    frames = len(audio) // FRAME
    samples = np.concatenate([np.round(audio * 32768.0), np.zeros(480)]).astype(np.float32)
    mel = np.vstack(
        [np.ones((WINDOW, MEL_BINS), dtype=np.float32), melspec(samples)[: STRIDE * frames]]
    )
    windows = np.stack([mel[STRIDE * (k + 1) : STRIDE * (k + 1) + WINDOW] for k in range(frames)])
    parts = [embed(windows[i : i + 256, :, :, None]) for i in range(0, frames, 256)]
    return np.concatenate(parts) if parts else np.zeros((0, EMBED_DIM), dtype=np.float32)


def one(row: dict[str, str]) -> tuple[str, np.ndarray]:
    return row["id"], clip_embeddings(read_wav(AUG / row["split"] / f"{row['id']}.wav"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()
    with (AUG / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    _init()
    prefix = primed()
    OUT.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for split in ("train", "val"):
        todo = [r for r in rows if r["split"] == split]
        found: dict[str, np.ndarray] = {}
        with mp.get_context("spawn").Pool(args.workers, initializer=_init) as pool:
            for n, (name, emb) in enumerate(pool.imap_unordered(one, todo, chunksize=16), 1):
                found[name] = emb
                if n % 1000 == 0:
                    print(f"  {split} {n}/{len(todo)}  {time.time() - start:.0f}s", flush=True)
        blocks = [np.vstack([prefix, found[r["id"]]]) for r in todo]
        sizes = np.array([len(b) - len(prefix) for b in blocks])
        np.savez(
            OUT / f"{split}.npz",
            emb=np.vstack(blocks),
            frames=sizes,
            prefix=len(prefix),
            ids=np.array([r["id"] for r in todo]),
            kind=np.array([r["kind"] for r in todo]),
            word_end_s=np.array(
                [float(r["word_end_s"]) if r["word_end_s"] else np.nan for r in todo]
            ),
        )
        print(
            f"{split}: {len(todo)} clips, {int(sizes.sum())} frames ({sizes.sum() * FRAME / RATE / 3600:.2f} h)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
