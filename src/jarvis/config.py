"""User settings from `config_dir()/config.toml`. Unknown keys are errors, never ignored."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.paths import config_dir


class ConfigError(ValueError):
    """The config file is unreadable, malformed, or has a bad or unknown key."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioSettings(_Section):
    device: str | None = None
    trailing_ms: int = Field(default=700, ge=400, le=1500)
    cap_s: int = 30


class WakeSettings(_Section):
    threshold: float = 0.005
    model: str = "hey_jarvis_v0.1"


class SttSettings(_Section):
    engine: Literal["whisper-server"] = "whisper-server"
    model: str = "base.en"
    server_bin: str | None = None
    threads: int = Field(default=4, ge=1)


class TtsSettings(_Section):
    engine: Literal["kokoro", "spd-say"] = "kokoro"


class BrainSettings(_Section):
    inactivity_reset_s: int = 600


class LogSettings(_Section):
    retention_days: int = 30


class Settings(_Section):
    audio: AudioSettings = Field(default_factory=AudioSettings)
    wake: WakeSettings = Field(default_factory=WakeSettings)
    stt: SttSettings = Field(default_factory=SttSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    log: LogSettings = Field(default_factory=LogSettings)


def load_settings(path: Path | None = None) -> Settings:
    """Read `path` (default `config_dir()/config.toml`); a missing file gives defaults."""
    path = path or config_dir() / "config.toml"
    if not path.exists():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return Settings.model_validate(data)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: invalid TOML: {error}") from error
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in error.errors()
        )
        raise ConfigError(f"{path}: {problems}") from error
