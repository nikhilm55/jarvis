"""User settings from `config_dir()/config.toml`. Unknown keys are errors, never ignored."""

import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import ErrorDetails

from jarvis.paths import config_dir
from jarvis.userconfig import InvalidNameError, clean_name


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


class UserSettings(_Section):
    # What Jarvis calls the user. Set in setup; never derived from the OS account. None = no name.
    name: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return clean_name(value)
        except InvalidNameError as error:
            raise ValueError(str(error)) from error


class HudSettings(_Section):
    python: str = "/usr/bin/python3"  # the system interpreter that has gi (GTK 3 + WebKit2 4.1)
    enabled: bool = True


class LogSettings(_Section):
    retention_days: int = Field(default=30, ge=1, le=3650)  # <= 0 would purge every record


# Folder -> consent-scope source (FRS 5.11): a shell path under one adds `<source>:read|write`.
DEFAULT_CONSENT_FOLDERS: dict[str, str] = {
    "~/Documents": "files.documents",
    "~/Desktop": "files.desktop",
    "~/Downloads": "files.downloads",
    "~/Pictures": "files.pictures",
}


class PolicySettings(_Section):
    """Allow/deny lists (FR-SAFE-09). A deny entry beats every tier, YOLO included."""

    deny_paths: list[str] = Field(default_factory=list)
    allow_paths: list[str] = Field(default_factory=list)  # only skips the consent-scope mapping
    deny_commands: list[str] = Field(default_factory=list)  # regexes, searched in the command line
    consent_folders: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_CONSENT_FOLDERS))

    @field_validator("deny_commands")
    @classmethod
    def _valid_regexes(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"{pattern!r} is not a valid regex: {error}") from error
        return patterns


class ConsentSettings(_Section):
    """Consent behaviour (FRS 5.11): how long a question waits and when grants expire."""

    ask_timeout_s: float = Field(default=15, gt=0, le=300)  # no answer in time is a no (FR-CON-07)
    always_expiry_days: int | None = Field(default=None, ge=1, le=3650)  # None: until revoked
    yolo_asks_first_touch: bool = False  # FR-CON-10: YOLO asks once per source when on


class Settings(_Section):
    audio: AudioSettings = Field(default_factory=AudioSettings)
    wake: WakeSettings = Field(default_factory=WakeSettings)
    stt: SttSettings = Field(default_factory=SttSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    hud: HudSettings = Field(default_factory=HudSettings)
    user: UserSettings = Field(default_factory=UserSettings)
    policy: PolicySettings = Field(default_factory=PolicySettings)
    consent: ConsentSettings = Field(default_factory=ConsentSettings)


def _describe(problem: ErrorDetails) -> str:
    where = ".".join(str(part) for part in problem["loc"])
    if where == "brain.address_as":  # removed key: say what to do, not just "extra inputs"
        return f"{where} was removed: delete it and run `jarvis setup --name <your name>`"
    return f"{where}: {problem['msg']}"


def load_settings(path: Path | None = None) -> Settings:
    """Read `path` (default `config_dir()/config.toml`); a missing file gives defaults."""
    path = path or config_dir() / "config.toml"
    if not path.exists():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return Settings.model_validate(data)
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path}: not valid UTF-8; open it and save it as UTF-8") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: invalid TOML: {error}") from error
    except ValidationError as error:
        problems = "; ".join(_describe(e) for e in error.errors())
        raise ConfigError(f"{path}: {problems}") from error
