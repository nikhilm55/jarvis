import wave
from pathlib import Path

import numpy as np
import pytest

from jarvis import models
from jarvis.cli import main
from tests.audio_utils import silence, tone


def test_should_list_the_four_subcommands_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in ("run", "say", "listen", "models"):
        assert command in out


@pytest.mark.parametrize(("command", "task"), [("run", 11), ("say", 5)])
def test_should_exit_2_with_not_built_message_when_command_is_a_stub(
    command: str, task: int, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command]) == 2
    assert capsys.readouterr().err.strip() == f"jarvis {command}: not built yet (M1 task {task})"


def test_should_print_every_model_without_network_when_dry_run(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network() -> object:
        raise AssertionError("dry run must not touch the network")

    monkeypatch.setattr(models, "_open_client", no_network)
    assert main(["models", "fetch", "--dry-run"]) == 0
    out = capsys.readouterr().out
    for spec in models.REGISTRY.values():
        assert spec.name in out
        assert spec.url in out
        assert str(models.model_path(spec)) in out


def test_should_limit_dry_run_to_named_models(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "fetch", "--dry-run", "whisper-tiny.en"]) == 0
    out = capsys.readouterr().out
    assert "whisper-tiny.en" in out
    assert "whisper-base.en" not in out


def test_should_exit_2_when_fetching_an_unknown_model(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "fetch", "--dry-run", "nope"]) == 2
    assert "whisper-base.en" in capsys.readouterr().err


def test_should_show_size_only_for_cached_models_when_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = models.REGISTRY["whisper-tiny.en"]
    target = models.model_path(spec)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * 2048)
    assert main(["models", "list"]) == 0
    lines = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert set(lines) == set(models.REGISTRY)
    assert "2.0 KB" in lines["whisper-tiny.en"]
    assert "KB" not in lines["whisper-base.en"]


def _fake_vad(monkeypatch: pytest.MonkeyPatch) -> None:
    """Energy VAD, so the CLI test needs no model file."""

    class EnergyVad:
        def prob(self, window: np.ndarray) -> float:
            return 0.9 if np.abs(window).max() > 1000 else 0.0

        def reset(self) -> None: ...

    monkeypatch.setattr("jarvis.cli.SileroVad", EnergyVad)


def test_should_print_the_utterance_summary_when_listening_to_a_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_vad(monkeypatch)
    pcm = np.concatenate([silence(1.0), tone(1.0), silence(1.0)])
    wav_path = tmp_path / "say.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm.tobytes())

    assert main(["listen", "--once", "--source", str(wav_path)]) == 0

    out = capsys.readouterr().out
    assert "silence_before_ms=992" in out  # 31 whole 32 ms windows of the 1.0 s lead-in
    assert "length=2.72s" in out  # 1.0 s pre-roll (all there is) + speech + 22 trailing windows
    assert "started_at=" in out and "ended_at=" in out


def test_should_exit_1_when_the_wav_has_no_speech(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_vad(monkeypatch)
    wav_path = tmp_path / "quiet.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(silence(1.0).tobytes())

    assert main(["listen", "--once", "--source", str(wav_path)]) == 1
    assert "no speech" in capsys.readouterr().err


def test_should_exit_2_when_the_wav_format_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_vad(monkeypatch)
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"junk")

    assert main(["listen", "--once", "--source", str(bad)]) == 2
    assert "not a readable WAV" in capsys.readouterr().err
