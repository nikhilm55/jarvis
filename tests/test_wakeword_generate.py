from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from types import ModuleType

import pytest

from tests.wakeword_loader import wakeword_modules

SENTENCES = [
    (f"{100 + i % 10}", f"This is sentence number {i} of the test corpus.") for i in range(300)
]


@pytest.fixture
def mods() -> Iterator[list[ModuleType]]:
    with wakeword_modules("texts", "generate") as loaded:
        yield loaded


def test_should_not_train_on_the_m0a_sound_alike_words_or_commands(mods: list[ModuleType]) -> None:
    words = {w.lower().split()[0] for w in mods[0].SOUND_ALIKES}
    assert not words & {
        "travis",
        "service",
        "nervous",
        "elvis",
        "davis",
        "garvey",
        "harvest",
        "jars",
    }
    assert not {c.lower() for c in mods[0].COMMANDS} & {
        "open settings",
        "stop",
        "take a screenshot",
    }


def test_should_plan_validation_clips_that_say_nothing_a_training_clip_says(
    mods: list[ModuleType],
) -> None:
    generate = mods[1]
    roster = [
        generate.Speaker("en_US-libritts_r-medium", str(i), "train" if i % 5 else "val")
        for i in range(50)
    ]
    assert {j.split for j in generate.plan(roster, 0.05, SENTENCES)} == {
        "train",
        "val",
    }  # asserts disjointness
    pools = generate.text_pools(SENTENCES)
    for key in ("sentences", "commands", "casual"):
        assert pools["train"][key] and not set(pools["train"][key]) & set(pools["val"][key])


def test_should_raise_when_a_validation_text_also_occurs_in_training(
    mods: list[ModuleType],
) -> None:
    generate = mods[1]
    roster = [
        generate.Speaker("en_US-libritts_r-medium", str(i), "train" if i else "val")
        for i in range(5)
    ]
    jobs = generate.plan(roster, 0.01, SENTENCES)
    train = next(j for j in jobs if j.split == "train" and j.kind == "speech")
    i = next(i for i, j in enumerate(jobs) if j.split == "val" and j.kind == "speech")
    jobs[i] = replace(jobs[i], text=train.text.lower())
    with pytest.raises(ValueError, match="validation texts also occur in training"):
        generate.assert_text_disjoint(jobs)
