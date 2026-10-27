"""The `[consent]` settings section (FR-CON-07, FR-CON-09, FR-CON-10)."""

from pathlib import Path

import pytest

from jarvis.config import ConfigError, ConsentSettings, Settings, load_settings


def _load(tmp_path: Path, body: str) -> Settings:
    path = tmp_path / "c.toml"
    path.write_text(body, encoding="utf-8")
    return load_settings(path)


def test_should_default_to_a_15_second_ask_no_expiry_and_no_yolo_first_touch() -> None:
    settings = Settings().consent
    assert settings == ConsentSettings()
    assert settings.ask_timeout_s == 15
    assert settings.always_expiry_days is None
    assert settings.yolo_asks_first_touch is False


def test_should_read_every_consent_key(tmp_path: Path) -> None:
    body = "[consent]\nask_timeout_s = 30\nalways_expiry_days = 90\nyolo_asks_first_touch = true\n"
    consent = _load(tmp_path, body).consent
    assert (consent.ask_timeout_s, consent.always_expiry_days) == (30, 90)
    assert consent.yolo_asks_first_touch is True


@pytest.mark.parametrize(
    "line", ["ask_timeout_s = 0", "ask_timeout_s = 301", "always_expiry_days = 0", "nope = 1"]
)
def test_should_reject_out_of_range_and_unknown_consent_keys(tmp_path: Path, line: str) -> None:
    with pytest.raises(ConfigError):
        _load(tmp_path, f"[consent]\n{line}\n")
