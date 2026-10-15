import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.desktop.volume import VolumeState

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "acceptance_m1", ROOT / "scripts" / "acceptance_m1.py"
)
assert spec and spec.loader
m1 = importlib.util.module_from_spec(spec)
sys.modules["acceptance_m1"] = m1
spec.loader.exec_module(m1)


def test_should_render_markdown_table_when_results_are_present() -> None:
    result = m1.IdleResult(
        label="silence",
        frames=10,
        segments=0,
        wall_s=1.0,
        cpu_s=0.05,
        percent=5.0,
    )
    table = m1.idle_table([result])
    assert "| silence |" in table
    assert "5.0" in table


class Audio:
    """A fake mixer: remembers what was set; `fail_volume` makes the volume call raise."""

    def __init__(self, percent: int, muted: bool, *, fail_volume: bool = False) -> None:
        self.state = VolumeState(percent, muted)
        self.fail_volume = fail_volume
        self.stuck_volume: int | None = None

    def get(self) -> VolumeState:
        return self.state

    def set_volume(self, percent: int) -> None:
        if self.fail_volume:
            raise OSError("wpctl failed")
        if self.stuck_volume is None:
            self.state = VolumeState(percent, self.state.muted)

    def set_mute(self, muted: bool) -> None:
        self.state = VolumeState(self.state.percent, muted)


def fake_audio(monkeypatch: pytest.MonkeyPatch, audio: Audio) -> None:
    monkeypatch.setattr(m1, "volume_get", audio.get)
    monkeypatch.setattr(m1, "volume_set", audio.set_volume)
    monkeypatch.setattr(m1, "set_mute", audio.set_mute)


def test_should_report_nothing_when_the_volume_and_mute_come_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = Audio(30, True)
    fake_audio(monkeypatch, audio)

    assert m1.restore_audio(VolumeState(58, False)) == []
    assert audio.state == VolumeState(58, False)


def test_should_still_restore_the_mute_when_the_volume_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = Audio(30, True, fail_volume=True)
    fake_audio(monkeypatch, audio)

    problems = m1.restore_audio(VolumeState(58, False))

    assert audio.state.muted is False
    assert len(problems) == 1
    assert "volume could not be restored" in problems[0]


def test_should_report_a_volume_that_reads_back_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = Audio(30, False)
    audio.stuck_volume = 30
    fake_audio(monkeypatch, audio)

    problems = m1.restore_audio(VolumeState(58, False))

    assert problems == ["volume is 30% after restoring, expected 58%"]


def test_should_fail_the_run_when_calculator_is_left_open() -> None:
    harness = SimpleNamespace(earcon_first=[], rows=[], hud=[])
    log = SimpleNamespace(turns=list)

    notes = m1.suite_notes(harness, log, None, True)

    assert "PROBLEM: Calculator was still open at the end" in notes


def test_should_not_fail_the_run_when_calculator_was_closed() -> None:
    harness = SimpleNamespace(earcon_first=[], rows=[], hud=[])
    log = SimpleNamespace(turns=list)

    notes = m1.suite_notes(harness, log, None, False)

    assert not any(n.startswith("PROBLEM") for n in notes)


@pytest.mark.parametrize(("text", "expected"), [("low", "low"), ("high", "high"), ("0.05", 0.05)])
def test_should_parse_the_output_latency_option(text: str, expected: str | float) -> None:
    assert m1.parse_latency(text) == expected
