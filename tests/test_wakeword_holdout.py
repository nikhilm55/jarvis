from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

from tests.wakeword_loader import wakeword_modules

M0A = [
    {"category": "jarvis_command", "text": "Jarvis, open Teams"},
    {"category": "jarvis_alone", "text": "Jarvis."},
    {"category": "confusable", "text": "Garvey, take a screenshot"},
    {"category": "negative_speech", "text": "Both products install and update independently."},
]


def clip(
    id_: str, text: str, command: str = "", *, kind: str = "pos", split: str = "train"
) -> dict[str, str]:
    return {"id": id_, "text": text, "command": command, "kind": kind, "split": split}


@pytest.fixture
def check() -> Iterator[ModuleType]:
    with wakeword_modules("check_holdout") as (module,):
        yield module


def test_should_pass_when_no_text_or_word_is_shared(check: ModuleType) -> None:
    synth = [clip("a", "Jarvis.", "lock the screen"), clip("b", "Marvin", "stop", kind="alike")]
    result = check.analyse(M0A, synth)
    assert result["composite_clips"] == [] and result["tail_clips"] == []
    assert result["warning_word_clips"] == 0


def test_should_flag_a_training_clip_that_says_an_m0a_composite_text(check: ModuleType) -> None:
    result = check.analyse(M0A, [clip("a", "Jarvis,", "open Teams"), clip("b", "Jarvis.")])
    assert result["composite_clips"] == ["a"]  # the bare wake word is shared by definition


def test_should_flag_a_command_that_is_an_m0a_command_tail_even_after_another_first_word(
    check: ModuleType,
) -> None:
    result = check.analyse(M0A, [clip("a", "Marvin", "Take a screenshot", kind="alike")])
    assert result["tail_clips"] == ["a"]
    assert result["tails"] == ["take a screenshot"]


def test_should_flag_a_validation_text_that_is_also_in_training(check: ModuleType) -> None:
    sentence = "The weather is lovely this morning."
    synth = [
        clip("t", sentence, kind="speech"),
        clip("v", sentence.lower(), kind="speech", split="val"),
        clip("w", "Jarvis.", split="val"),
    ]
    synth.append(clip("t2", "Jarvis."))
    assert check.analyse(M0A, synth)["val_in_train_clips"] == ["v"]


def test_should_not_count_a_bare_sound_alike_word_shared_by_both_splits(check: ModuleType) -> None:
    synth = [
        clip("t", "Carve us.", kind="alike"),
        clip("v", "carve us!", kind="alike", split="val"),
    ]
    assert check.analyse(M0A, synth)["val_in_train_clips"] == []


def test_should_only_warn_when_a_sound_alike_word_is_also_an_m0a_sound_alike_word(
    check: ModuleType,
) -> None:
    result = check.analyse(M0A, [clip("a", "Garvey.", "go ahead", kind="alike")])
    assert result["warning_word_clips"] == 1
    assert result["warning_words"] == ["garvey"]
    assert result["composite_clips"] == [] and result["tail_clips"] == []


def test_should_not_leave_the_modules_imported_after_the_test() -> None:
    with wakeword_modules("check_holdout", "speakers"):
        assert "check_holdout" in sys.modules
    assert "check_holdout" not in sys.modules
    assert "speakers" not in sys.modules
    assert "common" not in sys.modules
