"""Check jarvis.wake parity against M0a spike data.

Usage:
    python scripts/check_wake_parity.py [--all] [--per-category N]

Reads local, gitignored data under ~/Jarvis/spikes/M0a-wake-word/data.
"""

import argparse
import csv
import json
import sys
import wave
from collections import Counter
from pathlib import Path

import numpy as np

from jarvis.config import WakeSettings
from jarvis.wake.detector import WakeDetector
from jarvis.wake.gate import gate

DATA = Path.home() / "Jarvis" / "spikes" / "M0a-wake-word" / "data"
PARITY_TOLERANCE = 1e-3
CATEGORIES = [
    "jarvis_command",
    "jarvis_alone",
    "jarvis_mid_sentence",
    "confusable",
    "negative_speech",
]
EXPECTED_RATES = {
    "jarvis_command": 94.3,
    "jarvis_alone": 95.0,
    "jarvis_mid_sentence": 0.0,
    "confusable": 0.5,
}


def load_manifest() -> list[dict[str, str]]:
    """Read the clip manifest CSV."""
    rows: list[dict[str, str]] = []
    with open(DATA / "clips" / "manifest.csv", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_cached_scores() -> dict[str, float]:
    """Read cached openWakeWord scores."""
    with open(DATA / "cache" / "oww.json", encoding="utf-8") as f:
        cached = json.load(f)
    return dict(cached[0])


def load_transcripts() -> dict[str, str]:
    """Read cached Whisper transcripts."""
    with open(DATA / "cache" / "whisper-tiny.en-prompt.json", encoding="utf-8") as f:
        cached = json.load(f)
    return dict(cached[0])


def select_clips(
    rows: list[dict[str, str]],
    category: str,
    per_category: int,
    all_clips: bool,
) -> list[dict[str, str]]:
    """Pick clips for one category."""
    cat_rows = [r for r in rows if r["category"] == category]
    if all_clips:
        return cat_rows
    if len(cat_rows) <= per_category:
        return cat_rows
    idxs = np.linspace(0, len(cat_rows) - 1, per_category)
    picked = sorted({round(i) for i in idxs})
    return [cat_rows[i] for i in picked]


def read_wav(path: Path) -> np.ndarray:
    """Read a 16 kHz mono 16-bit PCM wav as int16."""
    with wave.open(str(path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16)


def score_clip(detector: WakeDetector, samples: np.ndarray) -> float:
    """Score one clip the way M0a did with upstream predict_clip."""
    detector.reset()
    data = np.concatenate(
        (np.zeros(16000, dtype=np.int16), samples, np.zeros(16000, dtype=np.int16))
    )
    best = 0.0
    for i in range(0, len(data) - 1280, 1280):
        best = max(best, float(detector.score(data[i : i + 1280])))
    return best


def run_detector_parity(
    rows: list[dict[str, str]],
    cached: dict[str, float],
    per_category: int,
    all_clips: bool,
) -> bool:
    """Score selected clips and compare to cached scores."""
    detector = WakeDetector()
    diffs: list[float] = []
    worst = ("", 0.0)
    count = 0
    for cat in CATEGORIES:
        for row in select_clips(rows, cat, per_category, all_clips):
            clip = row["clip"]
            path = DATA / "clips" / row["category"] / f"{clip}.wav"
            samples = read_wav(path)
            score = score_clip(detector, samples)
            ref = cached.get(clip, 0.0)
            d = abs(score - ref)
            diffs.append(d)
            if d > worst[1]:
                worst = (clip, d)
            count += 1
            if count % 10 == 0:
                print(f"scored {count} clips", file=sys.stderr)
    if not diffs:
        print("parity: 0 clips, max abs diff 0.00e+00, mean abs diff 0.00e+00, worst clip -")
        return True
    max_d = max(diffs)
    mean_d = float(np.mean(diffs))
    print(
        f"parity: {count} clips, max abs diff {max_d:.2e}, "
        f"mean abs diff {mean_d:.2e}, worst clip {worst[0]}"
    )
    ok = max_d <= PARITY_TOLERANCE
    print("PARITY PASS" if ok else "PARITY FAIL")
    return ok


def gate_rate(
    rows: list[dict[str, str]],
    cached: dict[str, float],
    transcripts: dict[str, str],
) -> dict[str, tuple[int, int]]:
    """Compute accepted/total per category using the gate."""
    threshold = WakeSettings().threshold
    counts: Counter[str] = Counter()
    accepted: Counter[str] = Counter()
    for row in rows:
        cat = row["category"]
        clip = row["clip"]
        counts[cat] += 1
        score = cached.get(clip, 0.0)
        transcript = transcripts.get(clip, "")
        if score >= threshold and gate(transcript).accepted:
            accepted[cat] += 1
    return {c: (accepted[c], counts[c]) for c in CATEGORIES}


def run_gate_rates(
    rows: list[dict[str, str]],
    cached: dict[str, float],
    transcripts: dict[str, str],
) -> bool:
    """Print gate rates and compare to expected table D."""
    rates = gate_rate(rows, cached, transcripts)
    ok = True
    for cat in CATEGORIES:
        acc, tot = rates[cat]
        rate = 100.0 * acc / tot if tot else 0.0
        print(f"{cat}: {acc}/{tot} = {rate:.1f}%")
        if cat == "negative_speech":
            if acc != 0:
                ok = False
        elif round(rate, 1) != EXPECTED_RATES[cat]:
            ok = False
    print("GATE PASS" if ok else "GATE FAIL")
    return ok


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Check jarvis.wake parity.")
    parser.add_argument("--all", action="store_true", help="use every manifest row")
    parser.add_argument(
        "--per-category", type=int, default=10, help="clips per category (default 10)"
    )
    return parser.parse_args()


def main() -> int:
    """Run both parity checks and return the exit code."""
    args = parse_args()
    if not DATA.exists():
        print(f"data directory missing: {DATA}", file=sys.stderr)
        return 2
    print(f"using data directory: {DATA}")
    rows = load_manifest()
    cached = load_cached_scores()
    transcripts = load_transcripts()
    parity_ok = run_detector_parity(rows, cached, args.per_category, args.all)
    gate_ok = run_gate_rates(rows, cached, transcripts)
    return 0 if (parity_ok and gate_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
