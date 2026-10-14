"""Synthetic audio for the audio tests: silence, noise, tones and a speech-like voice."""

import numpy as np

from jarvis.audio import SAMPLE_RATE
from jarvis.audio.sources import Pcm

_VOWELS = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480)]


def silence(seconds: float) -> Pcm:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)


def tone(seconds: float, hz: float = 440.0, amplitude: int = 8000) -> Pcm:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.int16)


def quiet_noise(seconds: float, seed: int = 0) -> Pcm:
    """Low-level noise (rms about 30): a distinctive, non-speech lead-in."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, 30, int(seconds * SAMPLE_RATE)).astype(np.int16)


def voice(seconds: float, seed: int = 0) -> Pcm:
    """A harmonic voice at ~120 Hz with vowel formants and a 4 Hz syllable rhythm."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    f0 = 120 + 15 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SAMPLE_RATE
    syllable = (t * 4).astype(int)
    out = np.zeros(n)
    for k in range(1, 40):
        freq = k * f0
        gain = np.zeros(n)
        for index, formants in enumerate(_VOWELS):
            mask = syllable % len(_VOWELS) == index
            resonance = sum(1 / (1 + ((freq - f) / 90) ** 2) for f in formants)
            gain += np.where(mask, resonance, 0.0)
        out += gain / k * np.sin(k * phase) * (freq < 4000)
    out *= 0.5 * (1 - np.cos(2 * np.pi * 4 * t)) / 2 + 0.5
    out += rng.normal(0, 0.02 * np.abs(out).max(), n)
    scaled: Pcm = (out / np.abs(out).max() * 9000).astype(np.int16)
    return scaled
