"""Diagnostic: the validation negatives (and positives) the trained classifier gets wrong, by kind and text.

uv run --no-project --python 3.11 --with numpy==2.4.6 --with torch==2.9.1 --extra-index-url https://download.pytorch.org/whl/cpu python tools/wakeword/errors.py [--threshold 0.5]
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys

import numpy as np
import torch
from common import DATA
from train import OUT, Classifier, Split


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    model = Classifier()
    model.load_state_dict(torch.load(OUT / "classifier.pt", weights_only=True))
    model.eval()
    val = Split("val")
    best = val.clip_max(val.scores(model))
    ids = np.load(DATA / "features" / "val.npz")["ids"]
    with (DATA / "aug" / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        info = {r["id"]: r for r in csv.DictReader(handle)}
    pos = val.kind == "pos"
    print(f"threshold {args.threshold}: recall {(best[pos] >= args.threshold).mean():.3f}")
    for kind in sorted(set(val.kind)):
        mask = val.kind == kind
        print(
            f"  {kind:7s} clips {mask.sum():4d}  >= threshold {(best[mask] >= args.threshold).sum():4d}"
        )
    words: collections.Counter[str] = collections.Counter()
    for i in np.argsort(-best):
        if val.kind[i] != "pos" and best[i] >= args.threshold:
            first = (info[str(ids[i])]["text"].split() or [str(val.kind[i])])[0]
            words[first.strip(".,!?").lower()] += 1
    print("first word of the false accepts:", words.most_common(20))
    miss = [info[str(ids[i])] for i in np.nonzero(pos)[0] if best[i] < args.threshold]
    print("missed positives (voice, params):", [(m["voice"], m["params"]) for m in miss[:8]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
