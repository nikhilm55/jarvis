from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Speaker:
    voice: str
    speaker: str
    split: str


def load_held_out(manifest_csv: Path) -> set[tuple[str, str]]:
    """Read every (voice, speaker) pair from the M0a evaluation manifest."""
    pairs: set[tuple[str, str]] = set()
    with manifest_csv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            voice = row["voice"]
            speaker = row["speaker"]
            pairs.add((voice, speaker))
    return pairs


def build_roster(
    voices: dict[str, int],
    held_out: set[tuple[str, str]],
    *,
    val_voices: frozenset[str] = frozenset(),
    val_fraction: float = 0.12,
    seed: int = 0,
) -> list[Speaker]:
    """Build the training roster of (voice, speaker) pairs, excluding held-out pairs."""
    roster: list[Speaker] = []
    for voice, num_speakers in voices.items():
        for idx in range(num_speakers):
            speaker = "" if num_speakers == 1 else str(idx)
            if (voice, speaker) in held_out:
                continue
            if voice in val_voices:
                split = "val"
            else:
                key = f"{seed}:{voice}:{speaker}".encode()
                digest = hashlib.sha256(key).hexdigest()[:8]
                bucket = int(digest, 16) / 2**32
                split = "val" if bucket < val_fraction else "train"
            roster.append(Speaker(voice=voice, speaker=speaker, split=split))
    roster.sort(key=lambda sp: (sp.voice, int(sp.speaker) if sp.speaker else 0))
    return roster


def assert_disjoint(roster: list[Speaker], held_out: set[tuple[str, str]]) -> None:
    """Raise ValueError if any roster pair appears in the held-out set."""
    for sp in roster:
        if (sp.voice, sp.speaker) in held_out:
            overlap = sum(1 for r in roster if (r.voice, r.speaker) in held_out)
            raise ValueError(
                f"Roster overlaps held-out set: first overlapping pair "
                f"({sp.voice!r}, {sp.speaker!r}), total overlapping pairs: {overlap}"
            )
