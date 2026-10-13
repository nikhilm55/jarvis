from pathlib import Path

import pytest

from jarvis.config import ConfigError, Settings, load_settings


def write_toml(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_should_have_default_hud_settings_when_no_config() -> None:
    settings = Settings()
    assert settings.hud.python == "/usr/bin/python3"
    assert settings.hud.enabled is True


def test_should_read_hud_settings_from_toml_when_valid(tmp_path: Path) -> None:
    path = write_toml(
        tmp_path / "config.toml",
        '[hud]\nenabled = false\npython = "/opt/py/bin/python3"\n',
    )
    settings = load_settings(path)
    assert settings.hud.enabled is False
    assert settings.hud.python == "/opt/py/bin/python3"


def test_should_raise_config_error_when_hud_has_unknown_key(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "config.toml", "[hud]\nbogus = 1\n")
    with pytest.raises(ConfigError, match=r"hud\.bogus"):
        load_settings(path)


def test_should_raise_config_error_when_hud_enabled_is_not_bool(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "config.toml", '[hud]\nenabled = "maybe"\n')
    with pytest.raises(ConfigError, match=r"hud\.enabled"):
        load_settings(path)
