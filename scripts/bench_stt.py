"""Benchmark the warm whisper.cpp server for tiny.en, base.en, small.en.

Reports, per model: p50/p95 latency, the share of clips whose first word is "Jarvis", and word
error rate against the reference texts of the M1 acceptance fixtures and the M0a clips.

Usage:
    uv run python scripts/bench_stt.py [--clips-dir DIR] [--count N] [--fixtures DIR]
        [--models tiny.en base.en small.en] [--threads N] [--prompt STR]
        [--limit-ms FLOAT]
"""

import argparse
import csv
import json
import re
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.audio.sources import SAMPLE_RATE, Pcm
from jarvis.models import ensure
from jarvis.orchestrator.listener import WAKE_PROMPT
from jarvis.stt import SttUnavailable, WhisperServer, find_server_bin

ROOT = Path(__file__).resolve().parent.parent
LATENCY_CLIP_S = (2.5, 3.5)  # the "3 s clip" band the FRS 7.1 local-CPU budget is quoted for


@dataclass(frozen=True)
class Clip:
    """One benchmark clip: audio, its reference text, and the corpus it belongs to."""

    corpus: str
    name: str
    pcm: Pcm
    text: str


@dataclass(frozen=True)
class Row:
    model: str
    n: int
    p50_ms: float
    p95_ms: float
    accuracy: float
    wer: dict[str, float]  # corpus name -> word error rate
    p50_3s_ms: float | None  # p50 over the clips inside LATENCY_CLIP_S


def _digit_to_words(n: int) -> list[str]:
    """English words for an integer 0-99 (inclusive)."""
    teens = [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    ]
    tens = [
        "",
        "",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
    ]
    ones = teens
    if n < 20:
        return [teens[n]]
    t, o = divmod(n, 10)
    words = [tens[t]]
    if o:
        words.append(ones[o])
    return words


def normalise_words(text: str) -> list[str]:
    """Words of `text` for scoring: lower case, no punctuation, 0-99 digits as words."""
    lowered = text.lower()
    lowered = lowered.replace("%", " percent")
    cleaned = "".join(ch for ch in lowered if ch.isalnum() or ch == "'" or ch.isspace())
    tokens = cleaned.split()
    result: list[str] = []
    for tok in tokens:
        if tok.isdigit() and (tok == "0" or not tok.startswith("0")) and 0 <= int(tok) <= 99:
            result.extend(_digit_to_words(int(tok)))
        else:
            result.append(tok)
    return result


def word_errors(reference: list[str], hypothesis: list[str]) -> int:
    """Word-level edit distance (substitutions + insertions + deletions)."""
    n = len(reference)
    m = len(hypothesis)
    dp: list[list[int]] = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[n][m]


def wer(references: list[str], hypotheses: list[str]) -> float:
    """Corpus word error rate: total word errors / total reference words."""
    if len(references) != len(hypotheses):
        raise ValueError("references and hypotheses must have the same length")
    total_errors = 0
    total_ref_words = 0
    for ref, hyp in zip(references, hypotheses, strict=True):
        ref_words = normalise_words(ref)
        hyp_words = normalise_words(hyp)
        total_errors += word_errors(ref_words, hyp_words)
        total_ref_words += len(ref_words)
    if total_ref_words == 0:
        return 0.0 if total_errors == 0 else float(total_errors)
    return total_errors / total_ref_words


def read_wav(path: Path) -> Pcm:
    """Mono 16 kHz int16 samples of a WAV file."""
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise SystemExit(f"error: {path} is not 16 kHz mono 16-bit")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def load_acceptance(fixtures: Path) -> list[Clip]:
    """The M1 acceptance fixtures with the text each was synthesised from."""
    manifest: dict[str, Any] = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    return [
        Clip("acceptance", name, read_wav(fixtures / f"{name}.wav"), entry["text"])
        for name, entry in sorted(manifest.items())
    ]


def load_m0a(clips_dir: Path, count: int) -> list[Clip]:
    """The first `count` M0a jarvis_command clips with their manifest reference text."""
    manifest = clips_dir / "manifest.csv"
    clips: list[Clip] = []
    with manifest.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["category"] != "jarvis_command":
                continue
            wav_path = clips_dir / row["category"] / f"{row['clip']}.wav"
            clips.append(Clip("m0a", row["clip"], read_wav(wav_path), row["text"]))
            if len(clips) >= count:
                break
    if len(clips) < count:
        raise SystemExit(f"error: only {len(clips)} jarvis_command clips found, need {count}")
    return clips


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values), q))


def bench_model(model: str, clips: list[Clip], server_bin: Path, threads: int, prompt: str) -> Row:
    """Run one warm-up then timed transcriptions for a single model."""
    model_path = ensure(f"whisper-{model}")
    with WhisperServer(model_path, server_bin, threads) as server:
        server.transcribe(clips[0].pcm, prompt)  # untimed warm-up
        ms: list[float] = []
        hits = 0
        wanted = 0
        heard: list[str] = []
        for clip in clips:
            t = server.transcribe(clip.pcm, prompt)
            ms.append(t.seconds * 1000.0)
            heard.append(t.text)
            if clip.text.lower().startswith("jarvis"):  # the wake word is expected first
                wanted += 1
                words = t.text.split()
                first = re.sub(r"[^a-z]", "", words[0].lower()) if words else ""
                hits += first == "jarvis"
    low, high = LATENCY_CLIP_S
    in_band = [m for m, c in zip(ms, clips, strict=True) if low <= len(c.pcm) / SAMPLE_RATE <= high]
    corpora = sorted({c.corpus for c in clips})
    scores = {}
    for corpus in corpora:
        pairs = [(c.text, h) for c, h in zip(clips, heard, strict=True) if c.corpus == corpus]
        scores[corpus] = wer([r for r, _ in pairs], [h for _, h in pairs])
    return Row(
        model=model,
        n=len(clips),
        p50_ms=percentile(ms, 50),
        p95_ms=percentile(ms, 95),
        accuracy=hits / wanted if wanted else 0.0,
        wer=scores,
        p50_3s_ms=percentile(in_band, 50) if in_band else None,
    )


def format_table(rows: list[Row]) -> str:
    """Render the benchmark results as an aligned plain-text table."""
    corpora = sorted({c for r in rows for c in r.wer})
    header = f"{'model':<10} {'clips':>5} {'p50 ms':>8} {'p95 ms':>8} {'p50 3s':>8} {'jarvis %':>9}"
    header += "".join(f" {'WER ' + c + ' %':>16}" for c in corpora)
    lines = [header, "-" * len(header)]
    for r in rows:
        p50_3s = f"{r.p50_3s_ms:>8.1f}" if r.p50_3s_ms is not None else f"{'n/a':>8}"
        line = f"{r.model:<10} {r.n:>5} {r.p50_ms:>8.1f} {r.p95_ms:>8.1f} {p50_3s} "
        line += f"{r.accuracy * 100:>9.1f}"
        line += "".join(f" {r.wer.get(c, float('nan')) * 100:>16.1f}" for c in corpora)
        lines.append(line)
    return "\n".join(lines)


def recommend(rows: list[Row], limit_ms: float) -> str | None:
    """Return the last model whose p50 on ~3 s clips (all clips if none) meets the limit."""
    p50s = [(r.model, r.p50_ms if r.p50_3s_ms is None else r.p50_3s_ms) for r in rows]
    fits = [model for model, p50 in p50s if p50 <= limit_ms]
    return fits[-1] if fits else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark whisper.cpp STT models")
    parser.add_argument(
        "--clips-dir",
        type=Path,
        default=Path("/home/fiftyfivetech/Jarvis/spikes/M0a-wake-word/data/clips"),
    )
    parser.add_argument("--count", type=int, default=40, help="M0a clips to use")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests" / "fixtures" / "acceptance")
    parser.add_argument("--models", nargs="+", default=["tiny.en", "base.en", "small.en"])
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--prompt", default=WAKE_PROMPT, help="default: the product's wake prompt")
    parser.add_argument("--limit-ms", type=float, default=800.0)
    args = parser.parse_args(argv)

    clips = [*load_acceptance(args.fixtures), *load_m0a(args.clips_dir, args.count)]
    mean_s = sum(len(c.pcm) for c in clips) / len(clips) / SAMPLE_RATE
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
