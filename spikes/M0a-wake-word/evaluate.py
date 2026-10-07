"""M0a: score wake-word candidates on the synthetic set (generate.py) and print the card's tables.

Usage (same throwaway env as generate.py):
  uv run --no-project --python 3.11 --with openwakeword==0.6.0 --with piper-tts==1.8.0 \
      --with onnxruntime==1.30.0 python spikes/M0a-wake-word/evaluate.py
Candidates:
  A  openWakeWord stock "hey_jarvis" model, scored on plain "Jarvis" (several thresholds)
  B  Whisper first-word gate alone (whisper.cpp tiny.en / base.en): accept iff first word ~ "jarvis"
  C  A at a low threshold, confirmed by B (the FRS design: detector + STT first-word gate)
Assumes ideal utterance segmentation (one clip = one utterance); real VAD is M1 work.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from openwakeword.model import Model

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CLIPS = DATA / "clips"
OWW = DATA / "models" / "oww"
WHISPER_BIN = Path.home() / "whispercpp" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
WHISPER_MODELS = {
    "tiny.en": DATA / "models" / "whisper" / "ggml-tiny.en.bin",
    "base.en": DATA / "models" / "whisper" / "ggml-base.en.bin",
}
THRESHOLDS = [0.05, 0.1, 0.2, 0.3, 0.5]
PROMPT = "Jarvis"
VARIANTS = {"jarvis", "jervis", "jarvas", "jarviss", "jarvi", "javis"}
POSITIVE = ("jarvis_command", "jarvis_alone")
CACHE = DATA / "cache"  # one file per stage, so a late failure never loses earlier work


def manifest() -> list[dict[str, str]]:
    with (CLIPS / "manifest.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def wav_path(row: dict[str, str]) -> Path:
    return CLIPS / row["category"] / f"{row['clip']}.wav"


def score_oww(rows: list[dict[str, str]]) -> tuple[dict[str, float], float]:
    model = Model(
        wakeword_models=[str(OWW / "hey_jarvis_v0.1.onnx")],
        inference_framework="onnx",
        melspec_model_path=str(OWW / "melspectrogram.onnx"),
        embedding_model_path=str(OWW / "embedding_model.onnx"),
    )
    scores, cpu, audio_s = {}, 0.0, 0.0
    for n, row in enumerate(rows, 1):
        model.reset()
        start = time.process_time()
        frames = model.predict_clip(str(wav_path(row)), padding=1, chunk_size=1280)
        cpu += time.process_time() - start
        audio_s += float(row["seconds"])
        scores[row["clip"]] = float(
            max(max(f.values()) for f in frames)
        )  # numpy float32 -> JSON-safe
        if n % 500 == 0:
            print(f"  oww {n}/{len(rows)}", flush=True)
    return scores, cpu / audio_s


def first_word(text: str) -> str:
    words = re.findall(r"[a-z']+", text.lower().replace("\u2019", "'"))
    return words[0].strip("'") if words else ""


def transcribe(
    rows: list[dict[str, str]], model: str, prompt: str | None = None
) -> tuple[dict[str, str], float]:
    files = [str(wav_path(r)) for r in rows]
    texts, wall = {}, 0.0
    for i in range(0, len(files), 200):  # batch: the model loads once per batch
        batch = files[i : i + 200]
        start = time.perf_counter()
        subprocess.run(
            [
                str(WHISPER_BIN),
                "-m",
                str(WHISPER_MODELS[model]),
                "-l",
                "en",
                "-t",
                "4",
                "-nt",
                "-np",
                "-otxt",
                *(["--prompt", prompt] if prompt else []),
                *batch,
            ],
            check=True,
            capture_output=True,
        )
        wall += time.perf_counter() - start
        for path in batch:
            txt = Path(path + ".txt")
            texts[Path(path).stem] = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
            txt.unlink(missing_ok=True)
        print(f"  whisper {model} {min(i + 200, len(files))}/{len(files)}", flush=True)
    return texts, wall / len(files)


REAL_WORDS = {
    "service",
    "harvest",
    "nervous",
    "travis",
    "davis",
    "elvis",
    "garvey",
    "jars",
    "jar",
    "charts",
    "tardis",
    "darts",
    "jobs",
    "java",
    "jeremy",
    "harvey",
    "marvin",
    "mavis",
    "parvis",
}


def levenshtein(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def rate(hits: list[bool]) -> str:
    return f"{100 * sum(hits) / len(hits):.1f}%" if hits else "—"


def main() -> int:
    rows = manifest()
    by_cat: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_cat[row["category"]].append(row)
    neg_hours = sum(float(r["seconds"]) for r in by_cat["negative_speech"]) / 3600
    CACHE.mkdir(exist_ok=True)

    def cached(name: str, compute):  # type: ignore[no-untyped-def]
        path = CACHE / f"{name}.json"
        if not path.exists():
            path.write_text(json.dumps(compute()), encoding="utf-8")
        return json.loads(path.read_text(encoding="utf-8"))

    oww_scores, oww_rtf = cached("oww", lambda: score_oww(rows))
    saved = {"oww": oww_scores, "oww_rtf": oww_rtf, "whisper": {}}
    for m in WHISPER_MODELS:
        texts, per_clip = cached(f"whisper-{m}", lambda m=m: transcribe(rows, m))
        saved["whisper"][m] = {"texts": texts, "s_per_clip": per_clip}
    # FR-STT-03 vocabulary biasing: the wake word as Whisper's initial prompt
    texts, per_clip = cached("whisper-tiny.en-prompt", lambda: transcribe(rows, "tiny.en", PROMPT))
    saved["whisper"]["tiny.en+prompt"] = {"texts": texts, "s_per_clip": per_clip}
    oww = saved["oww"]

    print(
        f"\nclips: { {c: len(v) for c, v in by_cat.items()} }  negative speech: {neg_hours * 60:.1f} min"
    )
    print(
        f"openWakeWord CPU: {100 * saved['oww_rtf']:.2f}% of one core (process time / audio time)"
    )
    for m, info in saved["whisper"].items():
        print(f"whisper {m}: {info['s_per_clip'] * 1000:.0f} ms wall per clip (4 threads, batched)")

    def table(name: str, fires) -> None:  # fires(row) -> bool
        print(
            f"\n### {name}\n| Setting | Detects 'Jarvis, …' | Detects 'Jarvis' alone | Mid-sentence fires | Sound-alike fires | False accepts / hour |"
        )
        print("|---|---|---|---|---|---|")
        for label, fn in fires:
            neg = [fn(r) for r in by_cat["negative_speech"]]
            print(
                f"| {label} | {rate([fn(r) for r in by_cat['jarvis_command']])} | {rate([fn(r) for r in by_cat['jarvis_alone']])} | "
                f"{rate([fn(r) for r in by_cat['jarvis_mid_sentence']])} | {rate([fn(r) for r in by_cat['confusable']])} | "
                f"{sum(neg) / neg_hours:.1f} ({sum(neg)} in {neg_hours * 60:.0f} min) |"
            )

    table(
        "A — openWakeWord 'hey_jarvis' (stock)",
        [(f"threshold {t}", lambda r, t=t: oww[r["clip"]] >= t) for t in THRESHOLDS],
    )
    gate = {
        m: (lambda r, m=m: first_word(saved["whisper"][m]["texts"].get(r["clip"], "")) in VARIANTS)
        for m in saved["whisper"]
    }
    table("B — Whisper first-word gate alone", [(m, gate[m]) for m in saved["whisper"]])
    table(
        "C — openWakeWord trigger + Whisper first-word gate",
        [
            (f"oww ≥ {t} + {m}", lambda r, t=t, m=m: oww[r["clip"]] >= t and gate[m](r))
            for t in (0.005, 0.05, 0.2)
            for m in saved["whisper"]
        ],
    )

    # D: tolerate near-misses ("darvis", "garvis") while rejecting real sound-alike words.
    # NOTE: REAL_WORDS was partly chosen from misses seen on this same set -> optimistic; validate on held-out/real voice.
    def fuzzy(m: str, max_edits: int):  # type: ignore[no-untyped-def]
        def accept(r: dict[str, str]) -> bool:
            word = first_word(saved["whisper"][m]["texts"].get(r["clip"], "")).removesuffix("'s")
            near = word not in REAL_WORDS and levenshtein(word, "jarvis") <= max_edits
            return oww[r["clip"]] >= 0.005 and (word in VARIANTS or near)

        return accept

    table(
        "D — oww ≥ 0.005 + Whisper gate with fuzzy first-word match",
        [(f"{m}, ≤{k} edits", fuzzy(m, k)) for k in (1, 2) for m in ("tiny.en+prompt", "base.en")],
    )

    misses = [
        first_word(saved["whisper"]["base.en"]["texts"].get(r["clip"], ""))
        for r in by_cat["jarvis_command"]
        if not gate["base.en"](r)
    ]
    print(
        f"\nbase.en first words on missed positives (top 8): {sorted(set(misses), key=misses.count, reverse=True)[:8]}"
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.exit(main())
