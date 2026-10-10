"""Tests for jarvis.stt.base."""

import dataclasses
import io
import wave
from pathlib import Path

import numpy as np
import pytest

from jarvis.stt.base import (
    SttUnavailable,
    Transcript,
    clean_transcript,
    encode_wav,
    find_server_bin,
)


def test_should_encode_wav_when_input_is_1d_int16() -> None:
    pcm = np.concatenate(
        [np.array([-32768, 32767], dtype=np.int16), np.arange(-100, 100, dtype=np.int16)]
    )
    data = encode_wav(pcm)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == len(pcm)
        assert np.frombuffer(wav.readframes(len(pcm)), dtype="<i2").tolist() == pcm.tolist()


def test_should_encode_zero_frame_wav_when_input_is_empty() -> None:
    data = encode_wav(np.empty(0, dtype=np.int16))
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnframes() == 0


def test_should_raise_value_error_when_input_is_2d() -> None:
    with pytest.raises(ValueError):
        encode_wav(np.zeros((2, 2), dtype=np.int16))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[BLANK_AUDIO]", ""),
        (" Jarvis,  open Teams. ", "Jarvis, open Teams."),
        ("(silence)", ""),
        ("Hello [MUSIC] there", "Hello there"),
        ("", ""),
        ("[ Silence ]", ""),
        ("♪ la la ♪", "la la"),
        ("[BLANK_AUDIO] (silence)", ""),
    ],
)
def test_should_clean_transcript_when_markers_present(raw: str, expected: str) -> None:
    assert clean_transcript(raw) == expected


def test_should_prefer_setting_when_env_and_path_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setting = tmp_path / "s"
    env = tmp_path / "e"
    path = tmp_path / "p"
    for p in (setting, env, path):
        p.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JARVIS_WHISPER_SERVER", str(env))
    monkeypatch.setattr("jarvis.stt.base.shutil.which", lambda _: str(path))
    assert find_server_bin(str(setting)) == setting


def test_should_prefer_env_when_setting_empty_and_path_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / "e"
    path = tmp_path / "p"
    env.write_text("x", encoding="utf-8")
    path.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JARVIS_WHISPER_SERVER", str(env))
    monkeypatch.setattr("jarvis.stt.base.shutil.which", lambda _: str(path))
    assert find_server_bin("") == env


def test_should_use_path_when_setting_and_env_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "p"
    path.write_text("x", encoding="utf-8")
    monkeypatch.delenv("JARVIS_WHISPER_SERVER", raising=False)
    monkeypatch.setattr("jarvis.stt.base.shutil.which", lambda _: str(path))
    assert find_server_bin(None) == path


def test_should_ignore_empty_string_setting_when_env_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / "e"
    env.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JARVIS_WHISPER_SERVER", str(env))
    monkeypatch.setattr("jarvis.stt.base.shutil.which", lambda _: None)
    assert find_server_bin("") == env


def test_should_raise_when_setting_points_to_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / "e"
    env.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JARVIS_WHISPER_SERVER", str(env))
    with pytest.raises(SttUnavailable):
        find_server_bin(str(tmp_path / "missing"))


def test_should_raise_when_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_WHISPER_SERVER", raising=False)
    monkeypatch.setattr("jarvis.stt.base.shutil.which", lambda _: None)
    with pytest.raises(SttUnavailable) as exc:
        find_server_bin(None)
    assert "whisper-server is not installed" in str(exc.value)
    assert exc.value.code == "STT_UNAVAILABLE"


def test_should_format_message_when_stt_unavailable_raised() -> None:
    err = SttUnavailable("no server", "install whisper")
    assert str(err) == "STT_UNAVAILABLE: no server. install whisper"
    assert err.reason == "no server"
    assert err.remedy == "install whisper"


def test_should_be_immutable_when_transcript_is_frozen() -> None:
    t = Transcript(text="hi", engine="whisper", seconds=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.text = "changed"  # type: ignore[misc]
