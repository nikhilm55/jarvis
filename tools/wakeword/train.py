"""Stage 5 — train: a small openWakeWord-style classifier on 16 embeddings, on CPU.

  uv run --no-project --python 3.11 --with numpy==2.4.6 --with torch==2.9.1 \
      --extra-index-url https://download.pytorch.org/whl/cpu python tools/wakeword/train.py [--epochs 14]

Reads data/features/{train,val}.npz. Windows: for clip frame k the classifier sees embeddings k-15..k
(the primed buffer fills in before the clip starts). Labels: a positive clip's frames whose end time lies in
[word_end - 0.08 s, word_end + 0.40 s] are positive; its frames from 0.24 s before the word's end up to that
window, and everything after it, are ignored (weight 0); every frame of a negative clip is negative. The first
5 frames are never scored (the detector's warm-up). Sound-alike negatives weigh 2; after each epoch negatives the
model still scores above 0.2 get their weight doubled (hard-negative mining, capped at 16).
The checkpoint kept is the epoch with the fewest validation false accepts at the threshold that still detects 99 % of the
validation positives; that threshold is the one reported (it is chosen on validation data only, never on M0a).
Writes data/model/classifier.pt and data/model/train.json (per-epoch validation numbers and the chosen threshold).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
import torch
from common import DATA, write_json
from torch import nn

N_FEATURES, EMBED_DIM, WARMUP = 16, 96, 5
FEATURES = DATA / "features"
OUT = DATA / "model"
FRAME_S = 0.08
FA_PER_HOUR_TARGET = 0.125  # FR-ACT-15: at most 1 false accept per 8 h


class Classifier(nn.Module):  # the architecture of openWakeWord's custom-model "dnn"
    def __init__(self, width: int = 128, dropout: float = 0.2) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(N_FEATURES * EMBED_DIM, width), nn.LayerNorm(width), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(width, width), nn.LayerNorm(width), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(width, 1), nn.Sigmoid(),
        )  # fmt: skip

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class Split:
    """One feature file as flat window indices: `end` is the exclusive end row of each window."""

    def __init__(self, name: str) -> None:
        z = np.load(FEATURES / f"{name}.npz")
        self.emb = torch.from_numpy(z["emb"])
        prefix, frames = int(z["prefix"]), z["frames"]
        kind, word_end = z["kind"], z["word_end_s"]
        starts = np.concatenate([[0], np.cumsum(frames + prefix)[:-1]])
        self.kind = kind
        self.clip_frames = frames
        end, clip, label, weight = [], [], [], []
        for c, (s, n) in enumerate(zip(starts, frames, strict=True)):
            k = np.arange(WARMUP, n)
            t = FRAME_S * (k + 1)
            if kind[c] == "pos":
                we = word_end[c]
                lab = ((t >= we - 0.08) & (t <= we + 0.40)).astype(np.float32)
                w = np.where(lab > 0, 1.0, np.where(t < we - 0.24, 1.0, 0.0)).astype(np.float32)
            else:
                lab = np.zeros(len(k), np.float32)
                w = np.full(len(k), 2.0 if kind[c] == "alike" else 1.0, np.float32)
            end.append(s + prefix + k + 1)
            clip.append(np.full(len(k), c))
            label.append(lab)
            weight.append(w)
        self.end = np.concatenate(end)
        self.clip = np.concatenate(clip)
        self.label = np.concatenate(label)
        self.weight = np.concatenate(weight)

    def batch(self, idx: np.ndarray) -> torch.Tensor:
        rows = self.end[idx][:, None] + np.arange(-N_FEATURES, 0)[None, :]
        return self.emb[torch.from_numpy(rows)]

    def scores(self, model: nn.Module, idx: np.ndarray | None = None) -> np.ndarray:
        idx = np.arange(len(self.end)) if idx is None else idx
        out = []
        with torch.no_grad():
            for i in range(0, len(idx), 8192):
                out.append(model(self.batch(idx[i : i + 8192])).squeeze(1).numpy())
        return np.concatenate(out)

    def clip_max(self, flat: np.ndarray) -> np.ndarray:
        """Per-clip max score over all scored frames (how M0a counts a detection)."""
        best = np.zeros(len(self.kind), np.float32)
        np.maximum.at(best, self.clip, flat)
        return best

    def hours(self, mask: np.ndarray) -> float:
        return float(self.clip_frames[mask].sum() * FRAME_S / 3600)


def evaluate(model: nn.Module, val: Split) -> dict[str, float]:
    """Validation numbers at two operating points: 99 % recall, and at most 1 false accept per 8 h."""
    best = val.clip_max(val.scores(model))
    pos = val.kind == "pos"
    neg_hours = val.hours(~pos)
    negatives = np.sort(best[~pos])[::-1]
    # the highest threshold that still detects 99 % of the validation positives
    t99 = float(np.sort(best[pos])[int(0.01 * pos.sum())])
    allowed = int(
        FA_PER_HOUR_TARGET * neg_hours
    )  # false accepts the target permits on this much audio
    t_fa = float(negatives[allowed]) + 1e-6  # the lowest threshold with <= `allowed` false accepts
    return {
        "threshold": t99,
        "fa_per_hour_at_threshold": float((best[~pos] >= t99).sum() / neg_hours),
        "threshold_fa_target": t_fa,
        "recall_at_fa_target": float((best[pos] >= t_fa).mean()),
        "recall_at_0.5": float((best[pos] >= 0.5).mean()),
        "fa_per_hour_at_0.5": float((best[~pos] >= 0.5).sum() / neg_hours),
        "neg_hours": neg_hours,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--epochs", type=int, default=14)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    train, val = Split("train"), Split("val")
    pos_idx = np.nonzero(train.label > 0)[0]
    neg_idx = np.nonzero((train.label == 0) & (train.weight > 0))[0]
    neg_w = train.weight.copy()
    print(
        f"train windows: {len(pos_idx)} positive, {len(neg_idx)} negative; val {len(val.end)}",
        flush=True,
    )
    model = Classifier()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    steps = args.epochs * (len(neg_idx) // 512)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=steps)
    history, best = [], (float("inf"), {})
    OUT.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for epoch in range(args.epochs):
        model.train()
        order = rng.permutation(neg_idx)
        for i in range(0, len(order) - 511, 512):
            neg = order[i : i + 512]
            pos = rng.choice(pos_idx, 256)
            idx = np.concatenate([neg, pos])
            x = train.batch(idx)
            y = torch.from_numpy(train.label[idx])
            w = torch.from_numpy(np.concatenate([neg_w[neg], np.full(256, 1.0, np.float32)]))
            loss = (
                nn.functional.binary_cross_entropy(model(x).squeeze(1), y, reduction="none") * w
            ).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
        model.eval()
        flat = train.scores(model, neg_idx)
        hard = flat > 0.2
        neg_w[neg_idx[hard]] = np.minimum(neg_w[neg_idx[hard]] * 2, 16.0)
        stats = evaluate(model, val)
        stats.update(
            epoch=epoch,
            loss=float(loss),
            hard_negatives=int(hard.sum()),
            seconds=round(time.time() - start),
        )
        history.append(stats)
        print(
            json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()}),
            flush=True,
        )
        if stats["fa_per_hour_at_threshold"] < best[0]:
            best = (stats["fa_per_hour_at_threshold"], stats)
            torch.save(model.state_dict(), OUT / "classifier.pt")
    write_json(OUT / "train.json", {"history": history, "chosen": best[1], "seed": args.seed})
    print(
        f"chosen epoch {best[1]['epoch']}: threshold {best[1]['threshold']:.4f} (99% val recall), "
        f"{best[0]:.2f} validation false accepts/h",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
