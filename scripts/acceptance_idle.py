"""Acceptance harness for measuring idle-path CPU and wall time."""

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np

from jarvis.audio.sources import SAMPLE_RATE, Pcm

__all__ = [
    "IdleResult",
    "measure_idle",
    "noise_pcm",
    "silence_pcm",
]


@dataclass(frozen=True)
class IdleResult:
    """Result of an idle-path measurement run."""

    label: str
    frames: int
    segments: int
    wall_s: float
    cpu_s: float
    percent: float


def silence_pcm(seconds: float) -> Pcm:
    """Return int16 zero samples for the given duration."""
    return np.zeros(round(seconds * SAMPLE_RATE), dtype=np.int16)


def noise_pcm(
    seconds: float,
    *,
    amplitude: int = 2000,
    seed: int = 0,
) -> Pcm:
    """Return uniform random int16 samples in [-amplitude, amplitude]."""
    rng = np.random.default_rng(seed)
    count = round(seconds * SAMPLE_RATE)
    return rng.integers(-amplitude, amplitude, size=count, dtype=np.int16, endpoint=True)


def measure_idle(
    label: str,
    frames: Iterable[Pcm],
    feed: Callable[[Pcm], int],
    *,
    cpu_clock: Callable[[], float] = time.process_time,
    wall_clock: Callable[[], float] = time.monotonic,
) -> IdleResult:
    """Run the idle pipeline over frames and report CPU/wall stats."""
    cpu_start = cpu_clock()
    wall_start = wall_clock()
    frame_count = 0
    segment_count = 0
    for frame in frames:
        segment_count += feed(frame)
        frame_count += 1
    cpu_end = cpu_clock()
    wall_end = wall_clock()
    wall_s = wall_end - wall_start
    cpu_s = cpu_end - cpu_start
    percent = round((cpu_s / wall_s) * 100.0, 2) if wall_s > 0 else 0.0
    return IdleResult(
        label=label,
        frames=frame_count,
        segments=segment_count,
        wall_s=wall_s,
        cpu_s=cpu_s,
        percent=percent,
    )
