from pathlib import Path

import pytest

from jarvis import paths
from jarvis.config import ConfigError, Settings, UserSettings, load_settings


def write_toml(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_should_return_documented_defaults_when_file_is_missing() -> None:
    settings = load_settings()
    assert settings == Settings()
    assert settings.audio.trailing_ms == 700
    assert settings.audio.cap_s == 30
    assert settings.audio.device is None
    assert (settings.wake.threshold, settings.wake.model) == (0.005, "hey_jarvis_v0.1")
    assert (settings.stt.engine, settings.stt.model) == ("whisper-server", "tiny.en")
    assert (settings.stt.server_bin, settings.stt.threads) == (None, 4)
    assert settings.tts.engine == "kokoro"
    assert (settings.tts.voice, settings.tts.speed) == ("bm_george", 1.0)
    assert settings.brain.inactivity_reset_s == 600
    assert settings.log.retention_days == 30


def test_should_read_config_dir_file_when_no_path_is_given() -> None:
    write_toml(paths.config_dir() / "config.toml", "[tts]\nengine = 'spd-say'\n")
    assert load_settings().tts.engine == "spd-say"


def test_should_override_only_what_the_file_sets(tmp_path: Path) -> None:
    path = write_toml(
        tmp_path / "c.toml", "[audio]\ntrailing_ms = 900\n[log]\nretention_days = 7\n"
    )
    settings = load_settings(path)
    assert settings.audio.trailing_ms == 900
    assert settings.audio.cap_s == 30
    assert settings.log.retention_days == 7


def test_should_name_the_key_when_an_unknown_key_is_present(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "c.toml", "[audio]\nfoo = 1\n")
    with pytest.raises(ConfigError, match=r"audio\.foo"):
        load_settings(path)


def test_should_reject_unknown_section(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "c.toml", "[nope]\nx = 1\n")
    with pytest.raises(ConfigError, match="nope"):
        load_settings(path)


@pytest.mark.parametrize("value", [399, 1501])
def test_should_reject_trailing_ms_outside_400_to_1500(tmp_path: Path, value: int) -> None:
    path = write_toml(tmp_path / "c.toml", f"[audio]\ntrailing_ms = {value}\n")
    with pytest.raises(ConfigError, match=r"audio\.trailing_ms"):
        load_settings(path)


def test_should_reject_unknown_engine(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "c.toml", "[stt]\nengine = 'cloud'\n")
    with pytest.raises(ConfigError, match=r"stt\.engine"):
        load_settings(path)


def test_should_name_the_file_when_toml_is_malformed(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "broken.toml", "[audio\n")
    with pytest.raises(ConfigError, match=r"broken\.toml"):
        load_settings(path)


def test_should_default_the_brain_session_settings_when_file_is_missing() -> None:
    brain = load_settings().brain
    assert (brain.model, brain.max_steps, brain.turn_timeout_s) == ("sonnet", 25, 120)
    assert brain.claude_bin is None


def test_should_read_brain_overrides_from_toml(tmp_path: Path) -> None:
    path = write_toml(
        tmp_path / "c.toml",
        "[brain]\nmodel = 'opus'\nmax_steps = 5\nturn_timeout_s = 30\nclaude_bin = '/opt/claude'\n",
    )
    brain = load_settings(path).brain
    assert (brain.model, brain.max_steps, brain.turn_timeout_s) == ("opus", 5, 30)
    assert brain.claude_bin == "/opt/claude"


@pytest.mark.parametrize("key", ["max_steps", "turn_timeout_s"])
def test_should_reject_a_non_positive_brain_limit(tmp_path: Path, key: str) -> None:
    path = write_toml(tmp_path / "c.toml", f"[brain]\n{key} = 0\n")
    with pytest.raises(ConfigError, match=rf"brain\.{key}"):
        load_settings(path)


def test_should_default_the_output_latency_to_high() -> None:
    assert Settings().tts.output_latency == "high"


@pytest.mark.parametrize(("literal", "expected"), [("'low'", "low"), ("0.05", 0.05)])
def test_should_read_the_output_latency(
    tmp_path: Path, literal: str, expected: str | float
) -> None:
    path = write_toml(tmp_path / "c.toml", f"[tts]\noutput_latency = {literal}\n")
    assert load_settings(path).tts.output_latency == expected


@pytest.mark.parametrize("literal", ["'medium'", "0", "-1.0", "5.0"])
def test_should_reject_a_bad_output_latency(tmp_path: Path, literal: str) -> None:
    path = write_toml(tmp_path / "c.toml", f"[tts]\noutput_latency = {literal}\n")
    with pytest.raises(ConfigError, match=r"tts\.output_latency"):
        load_settings(path)


def test_should_default_to_no_user_name_whatever_the_os_account_is() -> None:
    assert Settings().user == UserSettings(name=None)
    assert load_settings().user.name is None


@pytest.mark.parametrize(
    ("literal", "expected"), [("'Nikhil'", "Nikhil"), ("'  Ana  '", "Ana"), ("'José'", "José")]
)
def test_should_read_the_user_name_from_toml(tmp_path: Path, literal: str, expected: str) -> None:
    path = write_toml(tmp_path / "c.toml", f"[user]\nname = {literal}\n")
    assert load_settings(path).user.name == expected


@pytest.mark.parametrize("literal", ["''", "'   '", f"'{'a' * 41}'", '"a\\nb"', "5"])
def test_should_reject_a_bad_user_name(tmp_path: Path, literal: str) -> None:
    path = write_toml(tmp_path / "c.toml", f"[user]\nname = {literal}\n")
    with pytest.raises(ConfigError, match=r"user\.name"):
        load_settings(path)


def test_should_reject_the_removed_brain_address_as_key(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "c.toml", "[brain]\naddress_as = 'Nik'\n")
    with pytest.raises(ConfigError, match=r"brain\.address_as"):
        load_settings(path)
