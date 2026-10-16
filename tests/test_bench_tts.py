"""The TTS timeline arithmetic and its recording harness, with a fake engine (no audio)."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bench_tts", ROOT / "scripts" / "bench_tts.py")
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules["bench_tts"] = bench
spec.loader.exec_module(bench)


def test_should_report_no_gap_when_the_next_chunk_is_ready_before_the_last_ends() -> None:
    timeline = bench.playback_timeline([0.5, 1.0], [1.5, 2.0])
    assert timeline.first_audio_s == 0.5
    assert timeline.gaps_s == (0.0,)
    assert timeline.total_s == pytest.approx(0.5 + 1.5 + 2.0)


def test_should_report_dead_air_when_the_next_chunk_is_ready_after_the_last_ends() -> None:
    timeline = bench.playback_timeline([0.5, 3.0], [1.5, 2.0])  # chunk 1 ends at 2.0
    assert timeline.gaps_s == (pytest.approx(1.0),)
    assert timeline.total_s == pytest.approx(5.0)


def test_should_chain_three_chunks_from_where_each_previous_one_ends() -> None:
    timeline = bench.playback_timeline([1.0, 1.5, 6.0], [2.0, 1.0, 1.0])
    # chunk 1: 1-3; chunk 2 starts at 3 (ready 1.5), ends 4; chunk 3 ready at 6: 2 s of silence
    assert timeline.gaps_s == (0.0, pytest.approx(2.0))
    assert timeline.total_s == pytest.approx(7.0)


def test_should_have_no_gaps_for_a_single_chunk() -> None:
    timeline = bench.playback_timeline([0.7], [1.2])
    assert timeline.gaps_s == ()
    assert timeline.total_s == pytest.approx(1.9)


@pytest.mark.parametrize(("ready", "lengths"), [([], []), ([1.0], [1.0, 2.0])])
def test_should_reject_mismatched_or_empty_input(ready: list[float], lengths: list[float]) -> None:
    with pytest.raises(ValueError):
        bench.playback_timeline(ready, lengths)


class _TickEngine:
    """Takes a fixed time per call on a fake clock and returns audio of a fixed length."""

    sample_rate = 24000

    def __init__(self, clock: "_Clock", cost_s: float, audio_s: float) -> None:
        self._clock = clock
        self._cost = cost_s
        self._audio = audio_s

    def synthesize(self, text: str) -> np.ndarray:
        self._clock.now += self._cost
        return np.zeros(int(self.sample_rate * self._audio), dtype=np.float32)


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def test_should_measure_each_chunk_of_a_cut_reply_through_the_real_speaker() -> None:
    clock = _Clock()
    engine = _TickEngine(clock, cost_s=1.0, audio_s=0.5)  # slow synth, short audio: dead air
    reply = "That arrives in a later version, so for now I can open apps."
    timeline = bench.measure(engine, reply, clock)
    assert timeline.first_audio_s == pytest.approx(1.0)  # chunk 1 is ready after one synth
    assert timeline.gaps_s == (pytest.approx(0.5),)  # chunk 2 ready at 2.0, chunk 1 ended 1.5
    assert timeline.total_s == pytest.approx(2.5)


def test_should_summarise_first_audio_total_and_dead_air() -> None:
    line = bench.summary("x", [bench.Timeline(0.4, (0.2, 0.0), 3.0), bench.Timeline(0.6, (), 2.0)])
    assert "first audio p50 500 ms" in line
    assert "total p50 2.50 s" in line
    assert "worst 200 ms" in line
    assert "(2 gaps)" in line


def test_should_refuse_to_run_without_a_scratch_home(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    assert bench.main(["--repeats", "1"]) == 2
    assert "JARVIS_HOME" in capsys.readouterr().err
