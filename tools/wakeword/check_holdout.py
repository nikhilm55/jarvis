"""Proof that training did not see the M0a evaluation speakers (R72) or sentences, and that validation is text-disjoint.

  uv run --no-project --python 3.11 python tools/wakeword/check_holdout.py

Reads the generated clip manifest (data/synth), the augmented-clip manifest and the roster, and the M0a manifest
(`M0A_DATA` overrides its location). Exits 1, naming the overlap, on any of:
  - a (voice, speaker) pair in the roster, the generated clips or the augmented clips that M0a also uses;
  - a training composite text ("Jarvis, open Teams", a sentence) that is an M0a clip text;
  - a training command tail ("open Teams") that is an M0a command tail;
  - a validation text that also occurs in training.
Word-level overlap is only counted and printed as a warning: the first words of the training sound-alike clips that
are also M0a sound-alike words ("Garvey", "Service", ...). The bare wake word is shared by definition and ignored.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from common import DATA, M0A
from speakers import load_held_out

Row = dict[str, str]


def norm(text: str) -> str:
    """Lower-case words only: punctuation and spacing do not make two texts different."""
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def rows(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def train_text(row: Row) -> str:
    """What the clip says: the wake or sound-alike word, then the command if there is one."""
    return norm(f"{row['text']} {row['command']}")


def analyse(m0a: list[Row], synth: list[Row]) -> dict[str, object]:
    """Overlaps between the M0a texts and the generated clips, and between validation and training."""
    eval_texts = {norm(r["text"]) for r in m0a}
    eval_tails = {
        norm(r["text"].partition(",")[2])
        for r in m0a
        if r["category"] in ("jarvis_command", "confusable")
    }
    eval_words = {norm(r["text"]).split()[0] for r in m0a if r["category"] == "confusable"}
    trivial = {"", "jarvis"}  # the wake word on its own is shared by definition
    texts = {r["id"]: train_text(r) for r in synth}
    composites = {i for i, t in texts.items() if t in eval_texts and t not in trivial}
    tails = {r["id"] for r in synth if r["command"] and norm(r["command"]) in eval_tails}
    says = [
        r for r in synth if r["kind"] == "speech" or r["command"]
    ]  # not a bare wake or sound-alike word
    train = {texts[r["id"]] for r in says if r["split"] == "train"}
    leaked = {r["id"] for r in says if r["split"] == "val" and texts[r["id"]] in train}
    words = [r for r in synth if r["kind"] == "alike" and norm(r["text"]).split()[0] in eval_words]
    return {
        "composite_clips": sorted(composites),
        "tail_clips": sorted(tails),
        "tails": sorted({norm(r["command"]) for r in synth if r["id"] in tails}),
        "val_in_train_clips": sorted(leaked),
        "warning_word_clips": len(words),
        "warning_words": sorted({norm(r["text"]).split()[0] for r in words}),
    }


def pairs(clips: list[Row]) -> set[tuple[str, str]]:
    return {(r["voice"], r["speaker"]) for r in clips if r["voice"]}


def main() -> int:
    m0a = rows(M0A / "clips" / "manifest.csv")
    held_out = load_held_out(M0A / "clips" / "manifest.csv")
    synth = rows(DATA / "synth" / "manifest.csv")
    roster = {
        (s["voice"], s["speaker"])
        for s in json.loads((DATA / "synth" / "roster.json").read_text(encoding="utf-8"))
    }
    aug = DATA / "aug" / "manifest.csv"
    problems = []
    for name, found in (
        ("roster", roster),
        ("generated clips", pairs(synth)),
        ("augmented clips", pairs(rows(aug)) if aug.exists() else set()),
    ):
        both = found & held_out
        print(f"{name}: {len(found)} (voice, speaker) pairs, {len(both)} also in M0a")
        if both:
            problems.append(f"{name}: {len(both)} speaker pairs in M0a")
    result = analyse(m0a, synth)
    print(
        f"M0a: {len(held_out)} pairs, {len({norm(r['text']) for r in m0a})} distinct texts; {len(synth)} generated clips"
    )
    print(f"generated clips whose full text is an M0a clip text: {len(result['composite_clips'])}")  # type: ignore[arg-type]
    print(
        f"generated clips whose command is an M0a command: {len(result['tail_clips'])}  {result['tails']}"
    )  # type: ignore[arg-type]
    print(f"validation clips whose text is also in training: {len(result['val_in_train_clips'])}")  # type: ignore[arg-type]
    print(
        f"WARNING word-level: {result['warning_word_clips']} sound-alike clips start with an M0a sound-alike word {result['warning_words']}"
    )
    for key, label in (
        ("composite_clips", "M0a composite texts"),
        ("tail_clips", "M0a command tails"),
        ("val_in_train_clips", "validation texts also in training"),
    ):
        if result[key]:
            problems.append(f"{len(result[key])} clips with {label}")  # type: ignore[arg-type]
    if problems:
        print("HOLD-OUT VIOLATED: " + "; ".join(problems))
        return 1
    print(
        "HOLD-OUT OK: no M0a speaker pair, M0a text or M0a command in the clips, and validation texts are not in training"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
