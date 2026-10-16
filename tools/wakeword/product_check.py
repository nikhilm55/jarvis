"""Requirement 6: the product's WakeDetector scores the new model, and agrees with openWakeWord.

  uv run python tools/wakeword/product_check.py --model data/model/jarvis.onnx \
      --scores /tmp/m0a/cache/oww-custom-<hash>.json [--all | --per-category 10] [--threshold 0.5]

Runs in the project env (it imports jarvis.wake). The mel and embedding models are the files fetch.py downloaded; the
classifier is --model, passed to WakeDetector through its `Backends` hook, so the code under test is the detector the
product runs (streaming, 5-frame warm-up, replay, the R77 guard). The M0a clips are scored with the same procedure as
scripts/check_wake_parity.py and compared with the openWakeWord scores evaluate.py cached for the same model file.
Exit 1 if the largest difference exceeds 1e-3 (the tolerance the stock-model parity check uses).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnxruntime

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
from check_wake_parity import (  # noqa: E402
    CATEGORIES,
    DATA,
    load_manifest,
    read_wav,
    score_clip,
    select_clips,
)
from common import DATA as WORK  # noqa: E402
from common import read_json  # noqa: E402

from jarvis.wake.detector import Backends, WakeDetector  # noqa: E402

TOLERANCE = 1e-3


def session(path: Path) -> onnxruntime.InferenceSession:
    options = onnxruntime.SessionOptions()
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    return onnxruntime.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def backends(model: Path) -> Backends:
    mel_s, emb_s, clf_s = (
        session(WORK / "downloads" / "melspectrogram.onnx"),
        session(WORK / "downloads" / "embedding_model.onnx"),
        session(model),
    )
    mel_in, emb_in, clf_in = (s.get_inputs()[0].name for s in (mel_s, emb_s, clf_s))
    return Backends(
        mel=lambda x: np.asarray(mel_s.run(None, {mel_in: x})[0], dtype=np.float32).reshape(-1, 32),
        embed=lambda w: np.asarray(emb_s.run(None, {emb_in: w})[0], dtype=np.float32).reshape(
            w.shape[0], 96
        ),
        classify=lambda f: float(np.asarray(clf_s.run(None, {clf_in: f})[0]).reshape(-1)[0]),
        n_features=int(clf_s.get_inputs()[0].shape[1]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--scores", type=Path, required=True, help="evaluate.py's cached openWakeWord scores"
    )
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    cached = dict(read_json(args.scores)[0])
    detector = WakeDetector(backends=backends(args.model))
    rows = load_manifest()
    worst, diffs, hits = ("-", -1.0), [], {}
    for cat in CATEGORIES:
        picked = select_clips(rows, cat, args.per_category, args.all)
        fired = 0
        for row in picked:
            score = score_clip(detector, read_wav(DATA / "clips" / cat / f"{row['clip']}.wav"))
            d = abs(score - cached[row["clip"]])
            if len(diffs) < 5:
                print(
                    f"  {row['clip']}: product {score:.6f}  openWakeWord {cached[row['clip']]:.6f}"
                )
            diffs.append(d)
            worst = max(worst, (row["clip"], d), key=lambda p: p[1])
            fired += score >= args.threshold
        hits[cat] = (fired, len(picked))
    print(
        f"product vs openWakeWord: {len(diffs)} clips, max abs diff {max(diffs):.2e}, mean {np.mean(diffs):.2e}, worst {worst[0]}"
    )
    print(
        f"product WakeDetector fires at >= {args.threshold}: "
        + ", ".join(f"{c} {a}/{n}" for c, (a, n) in hits.items())
    )
    ok = max(diffs) <= TOLERANCE
    print("PRODUCT PARITY PASS" if ok else "PRODUCT PARITY FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
