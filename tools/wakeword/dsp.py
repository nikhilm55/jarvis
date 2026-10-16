"""Pure numpy DSP helpers for wake-word audio augmentation."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def rms(x: NDArray[np.float32]) -> float:
    """Root mean square of a signal; 0.0 for an empty array."""
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def colored_noise(kind: str, n: int, rng: np.random.Generator) -> NDArray[np.float32]:
    """Generate colored noise of the given kind with unit RMS.

    kind is "white", "pink" (power ~ 1/f) or "brown" (power ~ 1/f^2).
    """
    white = rng.normal(0.0, 1.0, size=n).astype(np.float64)

    if kind == "white":
        signal = white
    elif kind == "pink":
        signal = _shape_spectrum(white, n, slope=1.0)
    elif kind == "brown":
        signal = _shape_spectrum(white, n, slope=2.0)
    else:
        msg = f"Unknown noise kind: {kind!r}"
        raise ValueError(msg)

    r = rms(signal)
    if r == 0.0:
        return np.zeros(n, dtype=np.float32)
    return (signal / r).astype(np.float32)


def _shape_spectrum(white: NDArray[np.float64], n: int, slope: float) -> NDArray[np.float64]:
    """Shape the spectrum of white noise to the requested slope using FFT."""
    nfft = 1 << (n - 1).bit_length()
    spectrum = np.fft.rfft(white, n=nfft)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / n)
    freqs[0] = 1.0
    gain = freqs ** (
        -slope / 2.0
    )  # `slope` is the power exponent, so amplitude falls as f^(-slope/2)
    shaped = np.fft.irfft(spectrum * gain, n=nfft)[:n]
    return shaped


def tile_to(noise: NDArray[np.float32], n: int, rng: np.random.Generator) -> NDArray[np.float32]:
    """Return a length-n slice of noise: random start if longer, tiled repeat if shorter."""
    if len(noise) >= n:
        start = int(rng.integers(0, len(noise) - n + 1))
        return noise[start : start + n].copy()
    return np.resize(noise, n)


def mix_at_snr(
    speech: NDArray[np.float32],
    noise: NDArray[np.float32],
    snr_db: float,
) -> NDArray[np.float32]:
    """Return speech + g * noise where rms(speech)/rms(g*noise) == 10**(snr_db/20)."""
    speech_rms = rms(speech)
    noise_rms = rms(noise)
    if speech_rms == 0.0 or noise_rms == 0.0:
        return speech.copy()

    rng = np.random.default_rng(0)
    noise_tiled = tile_to(noise, len(speech), rng)
    noise_rms_tiled = rms(noise_tiled)
    if noise_rms_tiled == 0.0:
        return speech.copy()

    target_ratio = 10.0 ** (snr_db / 20.0)
    g = speech_rms / (target_ratio * noise_rms_tiled)
    return (speech + g * noise_tiled).astype(np.float32)


def synthetic_rir(
    rt60_s: float,
    rng: np.random.Generator,
    rate: int = 16000,
) -> NDArray[np.float32]:
    """Generate a synthetic room impulse response with a 60 dB decay tail."""
    tail_len = int(rt60_s * rate)
    h = np.zeros(tail_len + 1, dtype=np.float64)
    h[0] = 1.0

    t = np.arange(1, tail_len + 1, dtype=np.float64) / rate
    decay = np.exp(-6.9078 * t / rt60_s)
    tail = rng.normal(0.0, 1.0, size=tail_len) * decay

    direct_energy = h[0] ** 2
    target_tail_energy = direct_energy * 10.0 ** (-6.0 / 10.0)
    tail_energy = float(np.sum(tail**2))
    if tail_energy > 0.0:
        scale = np.sqrt(target_tail_energy / tail_energy)
        tail *= scale

    h[1:] = tail
    return h.astype(np.float32)


def apply_rir(audio: NDArray[np.float32], rir: NDArray[np.float32]) -> NDArray[np.float32]:
    """Convolve audio with RIR via FFT, keep first len(audio) samples, rescale RMS."""
    input_rms = rms(audio)
    if input_rms == 0.0:
        return audio.copy()

    n = len(audio)
    nfft = 1 << (n + len(rir) - 1 - 1).bit_length()
    audio_fft = np.fft.rfft(audio.astype(np.float64), n=nfft)
    rir_fft = np.fft.rfft(rir.astype(np.float64), n=nfft)
    convolved = np.fft.irfft(audio_fft * rir_fft, n=nfft)[:n]

    output_rms = rms(convolved)
    if output_rms == 0.0:
        return audio.copy()

    scaled = convolved * (input_rms / output_rms)
    return scaled.astype(np.float32)


def set_peak(audio: NDArray[np.float32], peak: float) -> NDArray[np.float32]:
    """Scale audio so that max(abs) equals peak; unchanged copy if max is 0."""
    max_val = float(np.max(np.abs(audio))) if audio.size > 0 else 0.0
    if max_val == 0.0:
        return audio.copy()
    return (audio * (peak / max_val)).astype(np.float32)
