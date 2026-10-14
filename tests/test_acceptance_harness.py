import importlib.util
import sys
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from jarvis.activity import TurnRecord
from jarvis.contract import FinalResponse
from jarvis.desktop.x11 import WindowInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "acceptance_harness", ROOT / "scripts" / "acceptance_harness.py"
)
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
sys.modules["acceptance_harness"] = harness
spec.loader.exec_module(harness)


@dataclass
class PlaybackStub:
    at: float


def _make_wav(path: Path, rate: int, seconds: float) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = int(rate * seconds)
        wf.writeframes(np.zeros(frames, dtype=np.int16).tobytes())


def test_should_return_true_when_wm_class_contains_calc() -> None:
    window = WindowInfo(
        window_id=1,
        wm_instance="gnome-calculator",
        wm_class="Gnome-calculator",
        pid=None,
        title="Calculator",
    )
    assert harness.is_calculator(window) is True


def test_should_return_false_when_title_mentions_calc_but_class_does_not() -> None:
    window = WindowInfo(
        window_id=1,
        wm_instance="gedit",
        wm_class="Gedit",
        pid=None,
        title="calc notes.txt",
    )
    assert harness.is_calculator(window) is False


def test_should_load_16khz_mono_wav_as_int16_array_when_valid(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _make_wav(wav_path, rate=16000, seconds=0.1)
    data = harness.load_wav(wav_path)
    assert data.dtype == np.int16
    assert len(data) == 1600


def test_should_raise_value_error_when_wav_sample_rate_is_8000(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _make_wav(wav_path, rate=8000, seconds=0.1)
    with pytest.raises(ValueError):
        harness.load_wav(wav_path)


def test_should_return_no_turn_failure_when_record_is_none() -> None:
    result = harness.judge("fastpath", None, None)
    assert result == "FAIL: no turn happened"


def test_should_return_route_mismatch_when_route_is_brain() -> None:
    record = TurnRecord(
        ts=datetime(2026, 10, 13, tzinfo=UTC),
        turn_id="t",
        raw_transcript="x",
        command="x",
        route="brain",
        final=FinalResponse(status="success", spoken="Done.", actions_taken=[]),
    )
    result = harness.judge("fastpath", record, None)
    assert result == "FAIL: route was brain, expected fastpath"


def test_should_return_failed_turn_when_final_is_none() -> None:
    record = TurnRecord(
        ts=datetime(2026, 10, 13, tzinfo=UTC),
        turn_id="t",
        raw_transcript="x",
        command="x",
        route="fastpath",
        final=None,
    )
    result = harness.judge("fastpath", record, None)
    assert result == "FAIL: the turn failed"


def test_should_return_problem_message_when_problem_is_set() -> None:
    record = TurnRecord(
        ts=datetime(2026, 10, 13, tzinfo=UTC),
        turn_id="t",
        raw_transcript="x",
        command="x",
        route="fastpath",
        final=FinalResponse(status="success", spoken="Done.", actions_taken=[]),
    )
    result = harness.judge("fastpath", record, "boom")
    assert result == "FAIL: boom"


def test_should_return_pass_when_route_and_final_are_valid() -> None:
    record = TurnRecord(
        ts=datetime(2026, 10, 13, tzinfo=UTC),
        turn_id="t",
        raw_transcript="x",
        command="x",
        route="fastpath",
        final=FinalResponse(status="success", spoken="Done.", actions_taken=[]),
    )
    result = harness.judge("fastpath", record, None)
    assert result == "PASS"


def test_should_return_none_when_playback_is_none() -> None:
    result = harness.ms_between(1.0, None)
    assert result is None


def test_should_return_rounded_milliseconds_when_playback_is_present() -> None:
    playback = PlaybackStub(at=1.5)
    result = harness.ms_between(1.0, playback)
    assert result == 500
