"""Synthetic audio for the audio tests: silence, noise, tones and a speech-like voice."""

import numpy as np

from jarvis.audio import SAMPLE_RATE
from jarvis.audio.sources import Pcm


def silence(seconds: float) -> Pcm:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)


def tone(seconds: float, hz: float = 440.0, amplitude: int = 8000) -> Pcm:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.int16)


def quiet_noise(seconds: float, seed: int = 0) -> Pcm:
    """Low-level noise (rms about 30): a distinctive, non-speech lead-in."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, 30, int(seconds * SAMPLE_RATE)).astype(np.int16)
