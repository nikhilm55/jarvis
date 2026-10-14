"""Tests for jarvis.config.load_settings bounds."""

from pathlib import Path

import pytest

from jarvis.config import ConfigError, load_settings


def _write_toml(tmp_path: Path, section: str, key: str, value: object) -> Path:
    """Write a minimal TOML file with a single section/key pair."""
    path = tmp_path / "c.toml"
    path.write_text(f"[{section}]\n{key} = {value}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("log", "retention_days", 1),
        ("audio", "cap_s", 2),
        ("brain", "inactivity_reset_s", 30),
        ("brain", "max_steps", 1),
        ("brain", "turn_timeout_s", 1),
        ("stt", "threads", 1),
        ("wake", "threshold", 0.0),
    ],
)
def test_should_accept_the_lowest_value_of_every_bound(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    """Accepts the lowest valid value for every bound."""
    path = _write_toml(tmp_path, section, key, value)
    settings = load_settings(path)
    assert getattr(getattr(settings, section), key) == value


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("log", "retention_days", 3650),
        ("audio", "cap_s", 300),
        ("brain", "inactivity_reset_s", 1800),
        ("brain", "max_steps", 200),
        ("brain", "turn_timeout_s", 3600),
        ("stt", "threads", 64),
        ("wake", "threshold", 1.0),
    ],
)
def test_should_accept_the_highest_value_of_every_bound(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    """Accepts the highest valid value for every bound."""
    path = _write_toml(tmp_path, section, key, value)
    settings = load_settings(path)
    assert getattr(getattr(settings, section), key) == value


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("log", "retention_days", -1),
        ("log", "retention_days", -100),
        ("audio", "cap_s", 0),
        ("audio", "cap_s", 1),
        ("brain", "inactivity_reset_s", 0),
        ("brain", "inactivity_reset_s", 29),
        ("brain", "max_steps", 0),
        ("brain", "turn_timeout_s", 0),
        ("stt", "threads", 0),
        ("wake", "threshold", -0.1),
    ],
)
def test_should_reject_a_value_below_the_bound(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    """Rejects values just below (or far below) the lowest bound."""
    path = _write_toml(tmp_path, section, key, value)
    with pytest.raises(ConfigError, match=rf"{section}\.{key}"):
        load_settings(path)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("log", "retention_days", 3651),
        ("audio", "cap_s", 301),
        ("brain", "inactivity_reset_s", 1801),
        ("brain", "max_steps", 201),
        ("brain", "turn_timeout_s", 3601),
        ("stt", "threads", 65),
        ("wake", "threshold", 1.5),
    ],
)
def test_should_reject_a_value_above_the_bound(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    """Rejects values just above the highest bound."""
    path = _write_toml(tmp_path, section, key, value)
    with pytest.raises(ConfigError, match=rf"{section}\.{key}"):
        load_settings(path)
