"""Tests for `jarvis run`: the CLI wiring around the Orchestrator.

Hook: `jarvis.cli.build_components` is replaced (monkeypatch) with a function that returns
fake components, so no microphone, speaker, whisper-server, model or Claude is needed.
"""

from pathlib import Path

import pytest

from jarvis import cli
from jarvis.audio import AudioFormatError, AudioSource
from jarvis.config import Settings
from jarvis.orchestrator.components import Components
from jarvis.policy import Mode
from tests.core_rig import CoreRig
from tests.listener_rig import seg


class Hook:
    """Stands in for `build_components` and remembers how it was called."""

    def __init__(self, parts: Components | Exception) -> None:
        self.parts = parts
        self.calls: list[tuple[AudioSource, Mode, bool]] = []

    async def __call__(
        self, settings: Settings, source: AudioSource, *, mode: Mode, with_brain: bool
    ) -> Components:
        self.calls.append((source, mode, with_brain))
        if isinstance(self.parts, Exception):
            raise self.parts
        return self.parts


def test_should_complete_a_fast_path_turn_end_to_end_with_no_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"], with_brain=False)
    rig.feed.push(seg())
    rig.feed.end()
    hook = Hook(rig.parts)
    monkeypatch.setattr(cli, "build_components", hook)

    code = cli.main(["run", "--source", str(tmp_path / "meeting.wav"), "--no-brain"])

    assert code == 0
    assert rig.speaker.said == ["Volume 40 percent."]
    out = capsys.readouterr().out
    assert "[acting] set the volume to 40" in out
    assert "[speaking] Volume 40 percent." in out
    assert hook.calls[0][1:] == ("balanced", False)
    assert rig.events[-1] == "service.close"


def test_should_pass_the_mode_and_keep_the_brain_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = CoreRig(tmp_path, [])
    rig.feed.end()
    hook = Hook(rig.parts)
    monkeypatch.setattr(cli, "build_components", hook)

    assert cli.main(["run", "--source", str(tmp_path / "x.wav"), "--mode", "yolo"]) == 0

    assert hook.calls[0][1:] == ("yolo", True)


def test_should_exit_2_with_a_message_when_a_component_cannot_be_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = Hook(AudioFormatError("bad.wav: not a readable WAV file"))
    monkeypatch.setattr(cli, "build_components", hook)

    code = cli.main(["run", "--source", str(tmp_path / "bad.wav"), "--no-brain"])

    assert code == 2
    assert capsys.readouterr().err.strip() == "jarvis run: bad.wav: not a readable WAV file"


def test_should_reject_an_unknown_mode(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", "--mode", "reckless"])
    assert exit_info.value.code == 2
