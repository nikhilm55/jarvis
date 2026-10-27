"""Acceptance tests for the idle module."""

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "acceptance_idle", ROOT / "scripts" / "acceptance_idle.py"
)
assert spec and spec.loader
idle = importlib.util.module_from_spec(spec)
sys.modules["acceptance_idle"] = idle
spec.loader.exec_module(idle)


def _make_fake_clock(values: list[float]) -> Callable[[], float]:
    """Build a callable that returns successive values from an iterator."""
    it: Iterator[float] = iter(values)
    return lambda: next(it)


def test_should_return_correct_length_and_zeros_when_silence_pcm_called() -> None:
    pcm = idle.silence_pcm(0.5)
    assert len(pcm) == round(0.5 * 16000)
    assert np.all(pcm == 0)


def test_should_return_correct_length_when_noise_pcm_called() -> None:
    pcm = idle.noise_pcm(0.25, amplitude=2000, seed=0)
    assert len(pcm) == round(0.25 * 16000)


def test_should_keep_values_within_bounds_when_noise_pcm_called() -> None:
    pcm = idle.noise_pcm(0.25, amplitude=2000, seed=0)
    assert np.all(pcm >= -2000)
    assert np.all(pcm <= 2000)


def test_should_be_deterministic_when_same_seed_used() -> None:
    a = idle.noise_pcm(0.25, amplitude=2000, seed=42)
    b = idle.noise_pcm(0.25, amplitude=2000, seed=42)
    assert np.array_equal(a, b)


def test_should_differ_when_different_seeds_used() -> None:
    a = idle.noise_pcm(0.25, amplitude=2000, seed=1)
    b = idle.noise_pcm(0.25, amplitude=2000, seed=2)
    assert not np.array_equal(a, b)


def test_should_count_frames_and_segments_when_measure_idle_called() -> None:
    frames = [1, 2, 3]
    feed_calls: list[int] = []

    def feed(frame: int) -> int:
        feed_calls.append(frame)
        return len(feed_calls) - 1

    result = idle.measure_idle(
        label="test",
        frames=frames,
        feed=feed,
        cpu_clock=lambda: 0.0,
        wall_clock=lambda: 0.0,
    )
    assert result.frames == 3
    assert result.segments == 3
    assert feed_calls == [1, 2, 3]


def test_should_compute_cpu_wall_and_percent_when_fake_clocks_advance() -> None:
    cpu_clock = _make_fake_clock([10.0, 10.6])
    wall_clock = _make_fake_clock([100.0, 120.0])
    frames = [1, 2, 3]

    def feed(frame: int) -> int:
        return 0

    result = idle.measure_idle(
        label="test",
        frames=frames,
        feed=feed,
        cpu_clock=cpu_clock,
        wall_clock=wall_clock,
    )
    assert result.cpu_s == pytest.approx(0.6)
    assert result.wall_s == 20.0
    assert result.percent == 3.0


def test_should_return_zero_percent_when_wall_s_is_zero() -> None:
    cpu_clock = _make_fake_clock([10.0, 10.6])
    wall_clock = _make_fake_clock([100.0, 100.0])
    frames = [1, 2, 3]

    def feed(frame: int) -> int:
        return 0

    result = idle.measure_idle(
        label="test",
        frames=frames,
        feed=feed,
        cpu_clock=cpu_clock,
        wall_clock=wall_clock,
    )
    assert result.percent == 0.0


def test_should_repeat_the_clip_to_the_requested_length_when_looping() -> None:
    clip = np.array([1, 2, 3], dtype=np.int16)
    looped = idle.loop_pcm(clip, 7 / 16000)
    assert looped.tolist() == [1, 2, 3, 1, 2, 3, 1]
    assert looped.dtype == np.int16


def test_should_return_nothing_when_looping_an_empty_clip() -> None:
    assert len(idle.loop_pcm(np.zeros(0, dtype=np.int16), 1.0)) == 0


def test_should_report_the_speech_share_of_vad_windows() -> None:
    run = idle.RoomIdle(idle.IdleResult("room", 10, 0, 1.0, 0.03, 3.0), 200, 5)
    assert run.speech_percent == 2.5
    assert idle.RoomIdle(run.result, 0, 0).speech_percent == 0.0
    assert "2.5% marked speech" in idle.idle_line(run)


def test_should_refuse_to_run_without_a_scratch_home(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    assert idle.main(["--seconds", "1"]) == 2
    assert "JARVIS_HOME" in capsys.readouterr().err
