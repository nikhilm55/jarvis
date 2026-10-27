"""Acceptance tests for the room-noise generator in acceptance_idle.py."""

import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "acceptance_idle_room", ROOT / "scripts" / "acceptance_idle.py"
)
assert spec and spec.loader
room = importlib.util.module_from_spec(spec)
sys.modules["acceptance_idle_room"] = room
spec.loader.exec_module(room)


def test_should_return_correct_length_and_dtype_when_room_noise_pcm_called() -> None:
    pcm = room.room_noise_pcm(0.5, seed=0)
    assert len(pcm) == round(0.5 * 16000)
    assert pcm.dtype == np.int16
    assert pcm.ndim == 1


def test_should_be_deterministic_when_same_seed_used() -> None:
    a = room.room_noise_pcm(0.5, seed=42)
    b = room.room_noise_pcm(0.5, seed=42)
    assert np.array_equal(a, b)


def test_should_differ_when_different_seeds_used() -> None:
    a = room.room_noise_pcm(0.5, seed=1)
    b = room.room_noise_pcm(0.5, seed=2)
    assert not np.array_equal(a, b)


def test_should_keep_rms_and_peak_within_bounds_when_no_clicks() -> None:
    pcm = room.room_noise_pcm(2.0, seed=0, clicks_per_s=0.0)
    rms = np.sqrt(np.mean((pcm.astype(np.float64) / 32767.0) ** 2))
    rms_db = 20.0 * np.log10(rms)
    peak = np.max(np.abs(pcm.astype(np.float64))) / 32767.0
    peak_db = 20.0 * np.log10(peak)
    assert abs(rms_db - (-50.0)) < 1.0
    assert peak_db < -35.0


def test_should_keep_peak_and_median_block_rms_within_bounds_when_default_clicks() -> None:
    pcm = room.room_noise_pcm(20.0, seed=0)
    peak = np.max(np.abs(pcm.astype(np.float64))) / 32767.0
    peak_db = 20.0 * np.log10(peak)
    assert abs(peak_db - (-35.0)) < 1.0

    block_size = round(0.1 * 16000)
    n_blocks = len(pcm) // block_size
    blocks = pcm[: n_blocks * block_size].reshape(n_blocks, block_size)
    block_rms = np.sqrt(np.mean((blocks.astype(np.float64) / 32767.0) ** 2, axis=1))
    block_rms_db = 20.0 * np.log10(block_rms)
    median_rms_db = np.median(block_rms_db)
    assert abs(median_rms_db - (-50.0)) < 1.5


def test_should_prefer_low_frequencies_over_high_when_no_clicks() -> None:
    pcm = room.room_noise_pcm(2.0, seed=0, clicks_per_s=0.0)
    signal = pcm.astype(np.float64)
    spectrum = np.fft.rfft(signal)
    magnitudes = np.abs(spectrum) ** 2
    freqs = np.fft.rfftfreq(len(signal), d=1.0 / 16000.0)

    low_mask = freqs <= 500.0
    high_mask = freqs >= 4000.0
    low_energy = np.sum(magnitudes[low_mask])
    high_energy = np.sum(magnitudes[high_mask])
    ratio_db = 10.0 * np.log10(low_energy / high_energy)
    assert ratio_db >= 10.0


def test_should_raise_rms_when_custom_floor_dbfs_used() -> None:
    pcm = room.room_noise_pcm(2.0, seed=0, clicks_per_s=0.0, floor_dbfs=-40.0)
    rms = np.sqrt(np.mean((pcm.astype(np.float64) / 32767.0) ** 2))
    rms_db = 20.0 * np.log10(rms)
    assert abs(rms_db - (-40.0)) < 1.0


def test_should_make_the_same_samples_as_the_per_bin_pink_filter() -> None:
    """Vectorising the 1/sqrt(f) filter must not change the signal."""
    rng = np.random.default_rng(3)
    white = rng.normal(0.0, 1.0, size=4000)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(4000, d=1.0 / 16000)
    slow = spectrum.copy()
    for i in range(1, len(slow)):
        slow[i] = slow[i] / np.sqrt(freqs[i])
    slow[0] = 0.0
    expected = np.fft.irfft(slow, n=4000)
    assert np.allclose(room._pink_noise(np.random.default_rng(3), 4000), expected)
