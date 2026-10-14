"""Benchmark the warm whisper.cpp server for tiny.en, base.en, small.en.

Usage:
    uv run python scripts/bench_stt.py [--clips-dir DIR] [--count N]
        [--models tiny.en base.en small.en] [--threads N] [--prompt STR]
        [--limit-ms FLOAT]
"""

import argparse
import csv
import re
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvis.audio.sources import SAMPLE_RATE, Pcm
from jarvis.models import ensure
from jarvis.stt import SttUnavailable, WhisperServer, find_server_bin


@dataclass(frozen=True)
class Row:
    model: str
    n: int
    p50_ms: float
    p95_ms: float
    accuracy: float


def load_clips(clips_dir: Path, count: int) -> list[Pcm]:
    """Load the first `count` jarvis_command clips from the manifest."""
    manifest = clips_dir / "manifest.csv"
    clips: list[Pcm] = []
    with manifest.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["category"] != "jarvis_command":
                continue
            wav_path = clips_dir / row["category"] / f"{row['clip']}.wav"
            with wave.open(str(wav_path), "rb") as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            clips.append(pcm)
            if len(clips) >= count:
                break
    if len(clips) < count:
        raise SystemExit(f"error: only {len(clips)} jarvis_command clips found, need {count}")
    return clips


def bench_model(model: str, clips: list[Pcm], server_bin: Path, threads: int, prompt: str) -> Row:
    """Run one warm-up then timed transcriptions for a single model."""
    model_path = ensure(f"whisper-{model}")
    with WhisperServer(model_path, server_bin, threads) as server:
        server.transcribe(clips[0], prompt)  # untimed warm-up
        ms: list[float] = []
        hits = 0
        for clip in clips:
            t = server.transcribe(clip, prompt)
            ms.append(t.seconds * 1000.0)
            words = t.text.split()
            first = re.sub(r"[^a-z]", "", words[0].lower()) if words else ""
            if first == "jarvis":
                hits += 1
    arr = np.asarray(ms)
    return Row(
        model=model,
        n=len(clips),
        p50_ms=float(np.percentile(arr, 50)),
        p95_ms=float(np.percentile(arr, 95)),
        accuracy=hits / len(clips),
    )


def format_table(rows: list[Row]) -> str:
    """Render the benchmark results as an aligned plain-text table."""
    header = f"{'model':<10} {'clips':>5} {'p50 ms':>8} {'p95 ms':>8} {'acc %':>7}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.model:<10} {r.n:>5} {r.p50_ms:>8.1f} {r.p95_ms:>8.1f} {r.accuracy * 100:>7.1f}"
        )
    return "\n".join(lines)


def recommend(rows: list[Row], limit_ms: float) -> str | None:
    """Return the last model whose p50 meets the latency limit, else None."""
    fits = [r.model for r in rows if r.p50_ms <= limit_ms]
    return fits[-1] if fits else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark whisper.cpp STT models")
    parser.add_argument(
        "--clips-dir",
        type=Path,
        default=Path("/home/fiftyfivetech/Jarvis/spikes/M0a-wake-word/data/clips"),
    )
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--models", nargs="+", default=["tiny.en", "base.en", "small.en"])
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--prompt", default="Jarvis")
    parser.add_argument("--limit-ms", type=float, default=800.0)
    args = parser.parse_args(argv)

    clips = load_clips(args.clips_dir, args.count)
    mean_s = sum(len(c) for c in clips) / len(clips) / SAMPLE_RATE
    print(f"{len(clips)} clips, mean length {mean_s:.2f} s, prompt {args.prompt!r}")

    try:
        server_bin = find_server_bin(None)
    except SttUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rows = [bench_model(m, clips, server_bin, args.threads, args.prompt) for m in args.models]
    print(format_table(rows))

    best = recommend(rows, args.limit_ms)
    if best:
        print(f"Recommendation: {best} (p50 <= {args.limit_ms:.0f} ms)")
    else:
        print(f"No model met the {args.limit_ms:.0f} ms p50 limit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
