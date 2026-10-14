"""Tests for Kokoro TTS engine additions in jarvis.tts.engines."""

import logging
import os
from typing import Any

import httpx
import numpy as np
import numpy.typing as npt
import pytest
from pydantic import ValidationError

from jarvis import models
from jarvis.config import TtsSettings
from jarvis.tts import engines
from jarvis.tts.engines import (
    AudioEngine,
    DirectEngine,
    KokoroEngine,
    SpdSayEngine,
    default_engine,
)

_OUTER_HOME = os.environ.get("JARVIS_HOME")


class FakeKokoro:
    """Fake Kokoro-like object that records create() calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._samples = np.zeros(24000, dtype=np.float64)

    def create(
        self,
        text: str,
        voice: str,
        speed: float,
        lang: str,
    ) -> tuple[npt.NDArray[np.float64], int]:
        self.calls.append({"text": text, "voice": voice, "speed": speed, "lang": lang})
        return self._samples, 24000


def test_should_pass_text_voice_speed_and_return_float32_when_synthesizing() -> None:
    fake = FakeKokoro()
    engine = KokoroEngine(fake, "bm_george", 1.0)
    result = engine.synthesize("Hello world")
    assert result.dtype == np.float32
    assert fake.calls[0]["text"] == "Hello world"
    assert fake.calls[0]["voice"] == "bm_george"
    assert fake.calls[0]["speed"] == 1.0


def test_should_use_lang_en_gb_when_voice_starts_with_b() -> None:
    fake = FakeKokoro()
    engine = KokoroEngine(fake, "bm_george", 1.0)
    engine.synthesize("Test")
    assert fake.calls[0]["lang"] == "en-gb"


def test_should_use_lang_en_us_when_voice_does_not_start_with_b() -> None:
    fake = FakeKokoro()
    engine = KokoroEngine(fake, "af_heart", 1.0)
    engine.synthesize("Test")
    assert fake.calls[0]["lang"] == "en-us"


def test_should_be_audio_engine_and_not_direct_engine_when_instantiated() -> None:
    fake = FakeKokoro()
    engine = KokoroEngine(fake, "bm_george", 1.0)
    assert isinstance(engine, AudioEngine)
    assert not isinstance(engine, DirectEngine)


def test_should_have_sample_rate_24000_when_instantiated() -> None:
    fake = FakeKokoro()
    engine = KokoroEngine(fake, "bm_george", 1.0)
    assert engine.sample_rate == 24000


def test_should_return_spd_say_engine_and_not_call_load_kokoro_when_engine_is_spd_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_assertion_error(settings: TtsSettings) -> KokoroEngine:
        raise AssertionError("_load_kokoro should not be called")

    monkeypatch.setattr(engines, "_load_kokoro", _raise_assertion_error)
    result = default_engine(TtsSettings(engine="spd-say"))
    assert isinstance(result, SpdSayEngine)


def test_should_return_loaded_engine_when_load_kokoro_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeKokoro()
    expected_engine = KokoroEngine(fake, "bm_george", 1.0)

    def _fake_load(settings: TtsSettings) -> KokoroEngine:
        return expected_engine

    monkeypatch.setattr(engines, "_load_kokoro", _fake_load)
    result = default_engine(TtsSettings(engine="kokoro"))
    assert result is expected_engine


@pytest.mark.parametrize(
    "error_type",
    [
        ImportError,
        OSError,
        RuntimeError,
        httpx.ConnectError,
        models.ModelIntegrityError,
    ],
)
def test_should_fallback_to_spd_say_and_log_warning_when_load_kokoro_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    def _raise_error(settings: TtsSettings) -> KokoroEngine:
        raise error_type("test failure")

    monkeypatch.setattr(engines, "_load_kokoro", _raise_error)
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        result = default_engine(TtsSettings(engine="kokoro"))
    assert isinstance(result, SpdSayEngine)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "spd-say" in warnings[0].message


def test_should_raise_unexpected_error_when_key_error_occurs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_key_error(settings: TtsSettings) -> KokoroEngine:
        raise KeyError("unexpected")

    monkeypatch.setattr(engines, "_load_kokoro", _raise_key_error)
    with pytest.raises(KeyError):
        default_engine(TtsSettings(engine="kokoro"))


def test_should_have_default_voice_and_speed_when_no_settings_specified() -> None:
    settings = TtsSettings()
    assert settings.voice == "bm_george"
    assert settings.speed == 1.0


@pytest.mark.parametrize("speed", [3.0, 0.1])
def test_should_raise_validation_error_when_speed_out_of_range(speed: float) -> None:
    with pytest.raises(ValidationError):
        TtsSettings(speed=speed)


@pytest.mark.model
def test_should_synthesize_real_audio_when_model_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if _OUTER_HOME is None:
        pytest.skip("JARVIS_HOME not set in outer environment")
    monkeypatch.setenv("JARVIS_HOME", _OUTER_HOME)
    if not models.is_cached(models.get_spec("kokoro-v1.0")) or not models.is_cached(
        models.get_spec("kokoro-voices-v1.0")
    ):
        pytest.skip("Kokoro models not cached")
    engine = engines._load_kokoro(TtsSettings())
    audio = engine.synthesize("Opening Calculator.")
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    duration = len(audio) / 24000
    assert 0.5 <= duration <= 5.0
    peak = np.max(np.abs(audio))
    assert 0.01 <= peak <= 1.0
