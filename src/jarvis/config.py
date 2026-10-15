"""User settings from `config_dir()/config.toml`. Unknown keys are errors, never ignored."""

import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.paths import config_dir


class ConfigError(ValueError):
    """The config file is unreadable, malformed, or has a bad or unknown key."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioSettings(_Section):
    device: str | None = None
    trailing_ms: int = Field(default=700, ge=400, le=1500)
    cap_s: int = Field(default=30, ge=2, le=300)


class WakeSettings(_Section):
    threshold: float = Field(default=0.005, ge=0, le=1)
    model: str = "hey_jarvis_v0.1"


class SttSettings(_Section):
    engine: Literal["whisper-server"] = "whisper-server"
    model: str = "tiny.en"
    server_bin: str | None = None
    threads: int = Field(default=4, ge=1, le=64)


class TtsSettings(_Section):
    engine: Literal["kokoro", "spd-say"] = "kokoro"
    voice: str = "bm_george"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    # PortAudio output latency. "low" stalls forever on ALSA over PipeWire (M1 acceptance F1).
    output_latency: Literal["low", "high"] | Annotated[float, Field(gt=0, le=2)] = "high"


class BrainSettings(_Section):
    # The MCP SDK reaps sessions idle for 30 minutes, so a longer reset would outlive the session.
    inactivity_reset_s: int = Field(default=600, ge=30, le=1800)
    model: str = "sonnet"  # M0b measured warm Sonnet
    max_steps: int = Field(default=25, ge=1, le=200)
    turn_timeout_s: int = Field(default=120, ge=1, le=3600)
    claude_bin: str | None = None
    address_as: str | None = None  # how Jarvis addresses the user; None = the OS user's first name


class HudSettings(_Section):
    python: str = "/usr/bin/python3"  # the system interpreter that has gi (GTK 3 + WebKit2 4.1)
    enabled: bool = True


class LogSettings(_Section):
    retention_days: int = Field(default=30, ge=1, le=3650)  # <= 0 would purge every record


class Settings(_Section):
    audio: AudioSettings = Field(default_factory=AudioSettings)
    wake: WakeSettings = Field(default_factory=WakeSettings)
    stt: SttSettings = Field(default_factory=SttSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    hud: HudSettings = Field(default_factory=HudSettings)


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
