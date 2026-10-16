"""TTS timing without playing audio: first audio, the gap between chunks, total speaking time.

Runs the product's Speaker with the real engine and a sink that discards audio. The timeline of
what a listener would hear is rebuilt from when each chunk finished synthesising and how long it
lasts: a chunk starts when it is ready or when the previous one ends, whichever is later, and the
wait in between is dead air.

Usage (JARVIS_HOME must be a scratch home that holds the models):
    uv run python scripts/bench_tts.py [--repeats N] [--sentences-only]
"""

import argparse
import contextlib
import os
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from unittest import mock

from jarvis.config import TtsSettings
from jarvis.tts import Speaker
from jarvis.tts import speaker as speaker_module
from jarvis.tts.engines import AudioEngine, Pcm, default_engine
from jarvis.tts.text import split_sentences

REPLIES = (
    "Opening Calculator.",
    "It's ten forty two.",
    "Done. I opened Calculator and set the volume to forty percent for you.",
    "I can't run commands or create files yet. That arrives in a later version.",
    "That arrives in a later version, so for now I can open apps and change the volume.",
    "Sure, I can do that, but first I need to know which window you mean.",
)


@dataclass(frozen=True)
class Timeline:
    """What a listener hears for one reply, in seconds from the call to `say`."""

    first_audio_s: float
    gaps_s: tuple[float, ...]  # dead air before each chunk after the first
    total_s: float  # from the call to the end of the last chunk


def playback_timeline(ready_s: Sequence[float], durations_s: Sequence[float]) -> Timeline:
    """Rebuild the heard timeline from each chunk's ready time and audio length."""
    if len(ready_s) != len(durations_s) or not ready_s:
        raise ValueError("need one ready time and one duration per chunk, at least one")
    ends = 0.0
    gaps: list[float] = []
    for index, (ready, length) in enumerate(zip(ready_s, durations_s, strict=True)):
        start = ready if index == 0 else max(ready, ends)
        if index:
            gaps.append(start - ends)
        ends = start + length
    return Timeline(first_audio_s=ready_s[0], gaps_s=tuple(gaps), total_s=ends)


class _RecordingEngine:
    """Wraps an AudioEngine; notes when each chunk finished and how long its audio lasts."""

    def __init__(self, engine: AudioEngine, clock: Callable[[], float]) -> None:
        self.sample_rate = engine.sample_rate
        self._engine = engine
        self._clock = clock
        self.chunks: list[tuple[float, float]] = []  # (finished at, audio seconds)

    def synthesize(self, text: str) -> Pcm:
        audio = self._engine.synthesize(text)
        self.chunks.append((self._clock(), len(audio) / self.sample_rate))
        return audio


class _NullSink:
    def __init__(self, rate: int) -> None:
        self.rate = rate

    def write(self, block: Pcm) -> None:
        return None

    def abort(self) -> None:
        return None

    def close(self) -> None:
        return None


def measure(
    engine: AudioEngine, reply: str, clock: Callable[[], float] = time.monotonic
) -> Timeline:
    """Speak `reply` through a real Speaker and a silent sink; return what would be heard."""
    recorder = _RecordingEngine(engine, clock)
    speaker = Speaker(TtsSettings(), engine_factory=lambda: recorder, sink_factory=_NullSink)
    try:
        started = clock()
        speaker.say(reply).wait(60)
    finally:
        speaker.close()
    ready = [finished - started for finished, _ in recorder.chunks]
    lengths = [seconds for _, seconds in recorder.chunks]
    return playback_timeline(ready, lengths)


def summary(label: str, timelines: Sequence[Timeline]) -> str:
    """One line: p50 first audio, p50 total, and the worst and mean dead air between chunks."""
    gaps = [g for t in timelines for g in t.gaps_s]
    worst = max(gaps, default=0.0)
    mean = statistics.fmean(gaps) if gaps else 0.0
    first = statistics.median(t.first_audio_s for t in timelines) * 1000
    return (
        f"{label}: first audio p50 {first:.0f} ms, "
        f"total p50 {statistics.median(t.total_s for t in timelines):.2f} s, "
        f"dead air between chunks mean {mean * 1000:.0f} ms, worst {worst * 1000:.0f} ms "
        f"({len(gaps)} gaps)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run every reply `--repeats` times and print one line per reply and an overall one."""
    parser = argparse.ArgumentParser(description="TTS first audio, gaps and total, no audio.")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sentences-only", action="store_true", help="the old splitting")
    args = parser.parse_args(argv)
    if not os.environ.get("JARVIS_HOME"):
        print(
            "bench_tts: set JARVIS_HOME to a scratch home (never your real data)", file=sys.stderr
        )
        return 2
    engine = default_engine(TtsSettings())
    if not isinstance(engine, AudioEngine):
        print("bench_tts: the Kokoro engine is not available", file=sys.stderr)
        return 2
    engine.synthesize("Ready.")
    every: list[Timeline] = []
    old = mock.patch.object(speaker_module, "split_for_speech", split_sentences)
    with old if args.sentences_only else contextlib.nullcontext():
        for reply in REPLIES:
            runs = [measure(engine, reply) for _ in range(args.repeats)]
            every += runs
            print(summary(reply[:42].ljust(42), runs))
    print(summary("ALL", every))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
