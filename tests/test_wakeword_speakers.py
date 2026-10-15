from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from tests.wakeword_loader import wakeword_modules


@pytest.fixture
def speakers() -> Iterator[ModuleType]:
    with wakeword_modules("speakers") as (module,):
        yield module


def test_should_read_every_voice_speaker_pair_when_loading_the_manifest(
    speakers: ModuleType, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "clip,category,text,voice,speaker,length_scale,noise,snr_db,seconds\n"
        "c1,cat,hello,en_US-lessac-medium,,1.0,0,0,1.0\n"
        "c2,cat,hi,en_US-libritts_r-medium,0,1.0,0,0,1.0\n"
        "c3,cat,hey,en_US-libritts_r-medium,1,1.0,0,0,1.0\n",
        encoding="utf-8",
    )
    pairs = speakers.load_held_out(manifest)
    assert ("en_US-lessac-medium", "") in pairs
    assert ("en_US-libritts_r-medium", "0") in pairs
    assert ("en_US-libritts_r-medium", "1") in pairs
    assert len(pairs) == 3


def test_should_exclude_held_out_pairs_when_building_the_roster(
    speakers: ModuleType, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "clip,category,text,voice,speaker,length_scale,noise,snr_db,seconds\n"
        "c1,cat,hello,en_US-lessac-medium,,1.0,0,0,1.0\n"
        "c2,cat,hi,en_US-libritts_r-medium,0,1.0,0,0,1.0\n",
        encoding="utf-8",
    )
    held_out = speakers.load_held_out(manifest)
    voices = {"en_US-lessac-medium": 1, "en_US-libritts_r-medium": 3}
    roster = speakers.build_roster(voices, held_out)
    for sp in roster:
        assert (sp.voice, sp.speaker) not in held_out
    assert not any(sp.voice == "en_US-lessac-medium" for sp in roster)
    assert not any(sp.voice == "en_US-libritts_r-medium" and sp.speaker == "0" for sp in roster)
    assert any(sp.voice == "en_US-libritts_r-medium" and sp.speaker == "1" for sp in roster)
    assert any(sp.voice == "en_US-libritts_r-medium" and sp.speaker == "2" for sp in roster)


def test_should_split_deterministically_when_building_the_roster(speakers: ModuleType) -> None:
    voices = {"big_voice": 900}
    held_out: set[tuple[str, str]] = set()
    roster = speakers.build_roster(voices, held_out, val_fraction=0.12, seed=42)
    roster2 = speakers.build_roster(voices, held_out, val_fraction=0.12, seed=42)
    assert roster == roster2
    val_count = sum(1 for sp in roster if sp.split == "val")
    total = len(roster)
    fraction = val_count / total
    assert 0.08 <= fraction <= 0.16


def test_should_put_val_voices_in_val_when_building_the_roster(speakers: ModuleType) -> None:
    voices = {"val_voice": 5, "train_voice": 5}
    held_out: set[tuple[str, str]] = set()
    roster = speakers.build_roster(voices, held_out, val_voices=frozenset({"val_voice"}))
    for sp in roster:
        if sp.voice == "val_voice":
            assert sp.split == "val"


def test_should_raise_when_the_roster_overlaps_the_held_out_set(speakers: ModuleType) -> None:
    held_out = {("en_US-lessac-medium", "")}
    roster = [speakers.Speaker(voice="en_US-lessac-medium", speaker="", split="train")]
    with pytest.raises(ValueError, match="en_US-lessac-medium"):
        speakers.assert_disjoint(roster, held_out)
    clean_roster = [speakers.Speaker(voice="other_voice", speaker="0", split="train")]
    speakers.assert_disjoint(clean_roster, held_out)
