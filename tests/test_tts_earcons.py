"""Tests for jarvis.tts.earcons."""

from __future__ import annotations

import numpy as np
import pytest

from jarvis.tts.earcons import EARCON_NAMES, EARCON_RATE, earcon_samples


@pytest.mark.parametrize("name", EARCON_NAMES)
def test_should_be_1d_float32_nonempty_under_300ms_when_name_is_valid(
    name: str,
) -> None:
    """Each earcon is a 1-D float32 array, non-empty, and < 300 ms."""
    samples = earcon_samples(name)

    assert samples.ndim == 1
    assert samples.dtype == np.float32
    assert len(samples) > 0
    duration = len(samples) / EARCON_RATE
    assert duration < 0.3


@pytest.mark.parametrize("name", EARCON_NAMES)
def test_should_have_subtle_audible_peak_when_name_is_valid(name: str) -> None:
    """Peak amplitude is audible but subtle: 0.02 < max(abs) <= 0.3."""
    samples = earcon_samples(name)

    peak = float(np.max(np.abs(samples)))

    assert 0.02 < peak <= 0.3


@pytest.mark.parametrize("name", EARCON_NAMES)
def test_should_have_near_zero_edges_when_name_is_valid(name: str) -> None:
    """First and last 5 samples have abs < 0.01 (no clicks)."""
    samples = earcon_samples(name)

    first_5 = np.abs(samples[:5])
    last_5 = np.abs(samples[-5:])

    assert np.all(first_5 < 0.01)
    assert np.all(last_5 < 0.01)


def test_should_be_distinct_when_comparing_all_four_earcons() -> None:
    """All four earcons are distinct from one another."""
    arrays = {name: earcon_samples(name) for name in EARCON_NAMES}

    names = list(arrays)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert not np.array_equal(arrays[names[i]], arrays[names[j]])


def test_should_be_identical_when_same_name_called_twice() -> None:
    """Same name twice gives identical arrays (deterministic)."""
    first = earcon_samples("wake")
    second = earcon_samples("wake")

    assert np.array_equal(first, second)


def test_should_not_mutate_internal_state_when_returned_array_is_modified() -> None:
    """Mutating the returned array doesn't change the next call's result."""
    first = earcon_samples("done")
    first[0] = 0.999

    second = earcon_samples("done")

    assert not np.array_equal(first, second)


def test_should_raise_value_error_mentioning_name_when_name_is_unknown() -> None:
    """Unknown name raises ValueError matching the name."""
    with pytest.raises(ValueError, match="bogus"):
        earcon_samples("bogus")


def test_should_contain_exactly_four_names_when_inspecting_earcon_names() -> None:
    """EARCON_NAMES is exactly those four names."""
    assert EARCON_NAMES == ("wake", "done", "error", "thinking")
