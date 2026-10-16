"""Tests for the wake-word DSP augmentation helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest


def _load() -> ModuleType:
    """Load the dsp module by file path and register it in sys.modules."""
    path = Path(__file__).resolve().parent.parent / "tools" / "wakeword" / "dsp.py"
    spec = importlib.util.spec_from_file_location("dsp", path)
    if spec is None or spec.loader is None:
        msg = f"Could not create import spec for {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dsp"] = module
    spec.loader.exec_module(module)
    return module


dsp = _load()


def test_should_have_unit_rms_when_generating_noise() -> None:
    """colored_noise should have RMS 1.0 (within 1%) for all valid kinds."""
    rng = np.random.default_rng(42)
    n = 16000 * 5
    for kind in ("white", "pink", "brown"):
        noise = dsp.colored_noise(kind, n, rng)
        assert noise.shape == (n,)
        rms_val = dsp.rms(noise)
        assert abs(rms_val - 1.0) < 0.01, f"{kind} noise RMS {rms_val} not within 1% of 1.0"


def test_should_slope_the_spectrum_when_generating_pink_and_brown_noise() -> None:
    """Pink noise: 100-200 Hz band power exceeds 2000-4000 Hz by 10-20 dB.
    White noise: two bands within 3 dB.
    Brown noise: low band exceeds high band by more than 25 dB."""
    rng = np.random.default_rng(123)
    n = 16000 * 5
    rate = 16000

    def band_power(signal: np.ndarray, lo: float, hi: float) -> float:
        """Mean power in a frequency band (Hz)."""
        spec = np.abs(np.fft.rfft(signal)) ** 2
        freqs = np.fft.rfftfreq(n, d=1.0 / rate)
        mask = (freqs >= lo) & (freqs < hi)
        return float(np.mean(spec[mask]))

    # Pink noise
    pink = dsp.colored_noise("pink", n, rng)
    pink_low = band_power(pink, 100, 200)
    pink_high = band_power(pink, 2000, 4000)
    pink_diff_db = 10.0 * np.log10(pink_low / pink_high)
    assert 10.0 <= pink_diff_db <= 20.0, f"Pink slope {pink_diff_db:.1f} dB not in [10, 20]"

    # White noise
    white = dsp.colored_noise("white", n, rng)
    white_low = band_power(white, 100, 200)
    white_high = band_power(white, 2000, 4000)
    white_diff_db = abs(10.0 * np.log10(white_low / white_high))
    assert white_diff_db < 3.0, f"White slope {white_diff_db:.1f} dB not within 3 dB"

    # Brown noise
    brown = dsp.colored_noise("brown", n, rng)
    brown_low = band_power(brown, 100, 200)
    brown_high = band_power(brown, 2000, 4000)
    brown_diff_db = 10.0 * np.log10(brown_low / brown_high)
    assert brown_diff_db > 25.0, f"Brown slope {brown_diff_db:.1f} dB not > 25 dB"


def test_should_reject_an_unknown_noise_kind() -> None:
    """colored_noise should raise ValueError for an unknown kind."""
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        dsp.colored_noise("purple", 1000, rng)


def test_should_hit_the_requested_snr_when_mixing() -> None:
    """mix_at_snr should yield a measured SNR within 0.1 dB of the request."""
    rng = np.random.default_rng(0)
    n = 16000 * 3
    speech = rng.normal(0.0, 1.0, size=n).astype(np.float32)
    for snr_db in (5.0, 10.0, 20.0):
        noise = dsp.colored_noise("white", n, rng)
        mixed = dsp.mix_at_snr(speech, noise, snr_db)
        # Measure SNR: rms(speech) / rms(mixed - speech)
        noise_part = mixed - speech
        measured_snr = 20.0 * np.log10(dsp.rms(speech) / dsp.rms(noise_part))
        assert abs(measured_snr - snr_db) < 0.1, (
            f"SNR {measured_snr:.2f} not within 0.1 dB of {snr_db}"
        )


def test_should_return_speech_unchanged_when_noise_is_silent() -> None:
    """mix_at_snr should return speech unchanged when noise RMS is 0."""
    rng = np.random.default_rng(0)
    n = 16000
    speech = rng.normal(0.0, 1.0, size=n).astype(np.float32)
    silent = np.zeros(n, dtype=np.float32)
    result = dsp.mix_at_snr(speech, silent, 10.0)
    np.testing.assert_array_equal(result, speech)


def test_should_return_n_samples_when_tiling_noise() -> None:
    """tile_to should return exactly n samples for both shorter and longer noise."""
    rng = np.random.default_rng(0)
    n = 16000 * 2

    # Shorter noise
    short = np.ones(100, dtype=np.float32)
    result_short = dsp.tile_to(short, n, rng)
    assert result_short.shape == (n,)

    # Longer noise
    long = np.ones(n * 2, dtype=np.float32)
    result_long = dsp.tile_to(long, n, rng)
    assert result_long.shape == (n,)


def test_should_decay_and_start_with_the_direct_path_when_making_an_rir() -> None:
    """synthetic_rir: correct length, h[0]==1.0, tail energy ~ -6 dB, decay in second half."""
    rng = np.random.default_rng(0)
    rt60 = 0.4
    rate = 16000
    rir = dsp.synthetic_rir(rt60, rng, rate)

    expected_len = int(rt60 * rate) + 1
    assert rir.shape == (expected_len,), f"RIR length {len(rir)} != {expected_len}"
    assert rir[0] == 1.0, "RIR[0] should be 1.0 (direct path)"

    # Tail energy relative to direct path
    tail = rir[1:]
    tail_energy = float(np.sum(tail**2))
    direct_energy = float(rir[0] ** 2)
    ratio_db = 10.0 * np.log10(tail_energy / direct_energy)
    assert abs(ratio_db - (-6.0)) < 1.0, f"Tail energy {ratio_db:.1f} dB not within 1 dB of -6 dB"

    # Second half of tail has far less energy than first half
    mid = len(tail) // 2
    first_half_energy = float(np.sum(tail[:mid] ** 2))
    second_half_energy = float(np.sum(tail[mid:] ** 2))
    assert second_half_energy < first_half_energy, "Second half should have less energy"


def test_should_keep_length_and_rms_when_applying_an_rir() -> None:
    """apply_rir should keep the same length and RMS as the input."""
    rng = np.random.default_rng(0)
    n = 16000 * 2
    audio = rng.normal(0.0, 1.0, size=n).astype(np.float32)
    rir = dsp.synthetic_rir(0.3, rng)
    result = dsp.apply_rir(audio, rir)
    assert result.shape == audio.shape, "Output length should match input"
    assert abs(dsp.rms(result) - dsp.rms(audio)) < 1e-3, "RMS should be preserved"


def test_should_leave_audio_unchanged_when_the_rir_is_an_impulse() -> None:
    """apply_rir with an identity RIR [1.0] should leave audio equal within 1e-4."""
    rng = np.random.default_rng(0)
    n = 16000
    audio = rng.normal(0.0, 1.0, size=n).astype(np.float32)
    impulse = np.array([1.0], dtype=np.float32)
    result = dsp.apply_rir(audio, impulse)
    np.testing.assert_allclose(result, audio, atol=1e-4)


def test_should_set_the_peak_when_scaling() -> None:
    """set_peak should scale so max(abs) equals the target peak."""
    rng = np.random.default_rng(0)
    n = 16000
    audio = rng.normal(0.0, 1.0, size=n).astype(np.float32)
    peak = 0.8
    result = dsp.set_peak(audio, peak)
    assert abs(float(np.max(np.abs(result))) - peak) < 1e-6, (
        f"Peak {np.max(np.abs(result))} not equal to {peak}"
    )


def test_should_be_deterministic_when_the_rng_is_seeded() -> None:
    """All functions should produce identical results with the same seed."""
    rng1 = np.random.default_rng(99)
    rng2 = np.random.default_rng(99)
    n = 16000 * 2

    noise1 = dsp.colored_noise("pink", n, rng1)
    noise2 = dsp.colored_noise("pink", n, rng2)
    np.testing.assert_array_equal(noise1, noise2)

    rir1 = dsp.synthetic_rir(0.4, rng1)
    rir2 = dsp.synthetic_rir(0.4, rng2)
    np.testing.assert_array_equal(rir1, rir2)

    speech = np.ones(n, dtype=np.float32) * 0.5
    mixed1 = dsp.mix_at_snr(speech, noise1, 10.0)
    mixed2 = dsp.mix_at_snr(speech, noise2, 10.0)
    np.testing.assert_array_equal(mixed1, mixed2)
