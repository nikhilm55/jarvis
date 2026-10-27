"""Acceptance harness for measuring idle-path CPU and wall time.

Also runnable: the idle mode feeds looped synthetic room noise (pink noise at -50 dBFS plus
occasional -35 dBFS clicks) through the product's capture chain (VAD, lazy wake detector,
segmenter) in real time and reports CPU and the share of VAD windows marked as speech.

    export JARVIS_HOME=/path/to/scratch/home   # holds the models; never your real data
    uv run python scripts/acceptance_idle.py [--seconds 60] [--loop-s 15] [--seed 0]
        [--input room|silence] [--profile]
"""

import argparse
import cProfile
import io
import os
import pstats
import sys
import time
import wave
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import numpy as np

from jarvis.audio.sources import SAMPLE_RATE, Pcm

__all__ = [
    "IdleResult",
    "RoomIdle",
    "loop_pcm",
    "main",
    "measure_idle",
    "noise_pcm",
    "room_noise_pcm",
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


def _pink_noise(rng: np.random.Generator, count: int) -> np.ndarray:
    """Return a pink-noise float array of the given length."""
    white = rng.normal(0.0, 1.0, size=count)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(count, d=1.0 / SAMPLE_RATE)
    spectrum[1:] /= np.sqrt(freqs[1:])
    spectrum[0] = 0.0
    return np.fft.irfft(spectrum, n=count)


def _click_burst(rng: np.random.Generator, peak: float) -> np.ndarray:
    """Return a 3 ms decaying Gaussian burst scaled to the given peak."""
    length = round(0.003 * SAMPLE_RATE)
    t = np.arange(length) / SAMPLE_RATE
    burst = rng.normal(0.0, 1.0, size=length) * np.exp(-t / 0.001)
    max_abs = np.max(np.abs(burst))
    if max_abs > 0.0:
        burst = burst * (peak / max_abs)
    return burst


def room_noise_pcm(
    seconds: float,
    *,
    seed: int = 0,
    floor_dbfs: float = -50.0,
    click_dbfs: float = -35.0,
    clicks_per_s: float = 0.25,
) -> Pcm:
    """Return a deterministic synthetic room-noise signal (pink noise plus clicks)."""
    rng = np.random.default_rng(seed)
    count = round(seconds * SAMPLE_RATE)
    signal = _pink_noise(rng, count)
    rms = np.sqrt(np.mean(signal**2))
    if rms > 0.0:
        target_rms = 32767.0 * 10.0 ** (floor_dbfs / 20.0)
        signal = signal * (target_rms / rms)

    n_clicks = round(seconds * clicks_per_s)
    if n_clicks >= 1:
        peak = 32767.0 * 10.0 ** (click_dbfs / 20.0)
        burst = _click_burst(rng, peak)
        positions = rng.integers(0, count, size=n_clicks)
        for pos in positions:
            end = min(pos + len(burst), count)
            signal[pos:end] = np.clip(signal[pos:end] + burst[: end - pos], -peak, peak)

    clipped = np.clip(signal, -32768.0, 32767.0)
    return np.asarray(clipped, dtype=np.int16)


def loop_pcm(clip: Pcm, seconds: float) -> Pcm:
    """Repeat `clip` end to end until it is `seconds` long (the last repeat is cut short)."""
    count = round(seconds * SAMPLE_RATE)
    if len(clip) == 0 or count <= 0:
        return np.zeros(0, dtype=np.int16)
    repeats = -(-count // len(clip))
    return np.tile(clip, repeats)[:count]


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


@dataclass(frozen=True)
class RoomIdle:
    """An idle run plus how often the VAD called the input speech."""

    result: IdleResult
    vad_windows: int
    vad_speech: int

    @property
    def speech_percent(self) -> float:
        """Share of VAD windows at or above the endpointer's start threshold, in percent."""
        return round(100.0 * self.vad_speech / self.vad_windows, 2) if self.vad_windows else 0.0


def _write_wav(path: Path, pcm: Pcm) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


def run_room_idle(
    scratch: Path, clip: Pcm, label: str, seconds: float, profile: bool = False
) -> tuple[RoomIdle, str]:
    """Feed `clip`, looped to `seconds`, through the real capture chain in real time.

    Returns the measurement and, with `profile`, a cProfile summary of the frame loop.
    """
    from jarvis.audio import WavFileSource  # noqa: PLC0415 - heavy imports only when run
    from jarvis.audio.endpointer import START_THRESHOLD  # noqa: PLC0415
    from jarvis.audio.vad import SileroVad  # noqa: PLC0415
    from jarvis.config import load_settings  # noqa: PLC0415
    from jarvis.orchestrator import assemble  # noqa: PLC0415

    calls = [0, 0]

    class CountingVad(SileroVad):
        def prob(self, window: Pcm) -> float:
            probability = super().prob(window)
            calls[0] += 1
            calls[1] += probability >= START_THRESHOLD
            return probability

    path = scratch / f"idle-{label.replace(' ', '-')}.wav"
    _write_wav(path, loop_pcm(clip, seconds))
    with mock.patch.object(assemble, "SileroVad", CountingVad):
        segmenter = assemble.build_segmenter(load_settings(), lambda: False)
    source = WavFileSource(path, realtime=True)
    profiler = cProfile.Profile() if profile else None
    if profiler is not None:
        profiler.enable()
    try:
        result = measure_idle(label, source.frames(), lambda frame: len(segmenter.feed(frame)))
    finally:
        if profiler is not None:
            profiler.disable()
        source.close()
    report = ""
    if profiler is not None:
        out = io.StringIO()
        pstats.Stats(profiler, stream=out).sort_stats("tottime").print_stats(12)
        report = out.getvalue()
    return RoomIdle(result, calls[0], calls[1]), report


def idle_line(run: RoomIdle) -> str:
    """One line for the acceptance note."""
    r = run.result
    return (
        f"{r.label}: {r.wall_s:.1f} s wall, {r.cpu_s:.2f} s CPU = {r.percent}% of one core; "
        f"{r.frames} frames, {run.vad_windows} VAD windows, {run.speech_percent}% marked speech; "
        f"{r.segments} segment events"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the idle mode and print its numbers."""
    parser = argparse.ArgumentParser(description="Idle CPU with live-like (synthetic) input.")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--loop-s", type=float, default=15.0, help="length of the looped clip")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--input", choices=("room", "silence"), default="room")
    parser.add_argument("--profile", action="store_true", help="print a cProfile summary")
    args = parser.parse_args(argv)
    home = os.environ.get("JARVIS_HOME")
    if not home:
        print("idle: set JARVIS_HOME to a scratch home (never your real data)", file=sys.stderr)
        return 2
    silent = args.input == "silence"
    clip = silence_pcm(args.loop_s) if silent else room_noise_pcm(args.loop_s, seed=args.seed)
    label = "silence" if silent else "room noise"
    run, report = run_room_idle(Path(home) / "idle", clip, label, args.seconds, args.profile)
    print(idle_line(run))
    if report:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
