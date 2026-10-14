"""Tests for the fast-path intent types."""

import dataclasses

import pytest

from jarvis.fastpath.intents import OpenApp, VolumeSet, VolumeStep


def test_should_be_frozen_when_assigning_to_an_intent() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(OpenApp("a"), "name", "b")  # noqa: B010


@pytest.mark.parametrize("value", [-1, 101])
def test_should_reject_when_volume_set_is_out_of_range(value: int) -> None:
    with pytest.raises(ValueError):
        VolumeSet(value)


@pytest.mark.parametrize("value", [0, 100])
def test_should_accept_when_volume_set_is_at_the_bounds(value: int) -> None:
    assert VolumeSet(value).percent == value


@pytest.mark.parametrize("value", [0, 5, 11])
def test_should_reject_when_volume_step_is_not_ten(value: int) -> None:
    with pytest.raises(ValueError):
        VolumeStep(value)


def test_should_reject_when_volume_set_is_a_bool() -> None:
    with pytest.raises(ValueError):
        VolumeSet(True)
