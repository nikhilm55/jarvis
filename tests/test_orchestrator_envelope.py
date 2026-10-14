"""Tests for jarvis.orchestrator.envelope."""

import datetime
import re

import pytest

from jarvis.config import BrainSettings, Settings
from jarvis.contract import TurnEnvelope
from jarvis.orchestrator.envelope import (
    build_envelope,
    display_server,
    first_name,
    locale_tag,
    new_turn_id,
    os_label,
    user_info,
)
from jarvis.stt import Transcript


def test_should_return_x11_when_environ_has_x11_session_type() -> None:
    assert display_server({"XDG_SESSION_TYPE": "x11"}) == "x11"


def test_should_return_wayland_when_environ_has_wayland_session_type() -> None:
    assert display_server({"XDG_SESSION_TYPE": "Wayland"}) == "wayland"


def test_should_return_none_when_environ_has_tty_session_type() -> None:
    assert display_server({"XDG_SESSION_TYPE": "tty"}) is None


def test_should_return_none_when_environ_has_no_session_type() -> None:
    assert display_server({}) is None


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LANG": "en_IN.UTF-8"}, "en-IN"),
        ({"LC_ALL": "de_DE.UTF-8", "LANG": "en_US.UTF-8"}, "de-DE"),
        ({"LANG": "C"}, "en-US"),
        ({"LANG": "POSIX"}, "en-US"),
        ({}, "en-US"),
        ({"LANG": "sr_RS@latin"}, "sr-RS"),
        ({"LC_ALL": "", "LANG": "en_GB.UTF-8"}, "en-GB"),
    ],
)
def test_should_return_expected_locale_tag_when_environ_has_given_values(
    environ: dict[str, str], expected: str
) -> None:
    assert locale_tag(environ) == expected


@pytest.mark.parametrize(
    ("gecos", "expected"),
    [
        ("Nikhil Malhotra,,,", "Nikhil"),
        ("", ""),
        (",,,", ""),
        ("  Ada Lovelace", "Ada"),
    ],
)
def test_should_return_expected_first_name_when_gecos_has_given_value(
    gecos: str, expected: str
) -> None:
    assert first_name(gecos) == expected


def test_should_prefer_address_as_setting_when_setting_is_present() -> None:
    info = user_info("Boss", "Nikhil Malhotra,,,", "nikhil")
    assert info.name == "Nikhil"
    assert info.address_as == "Boss"


def test_should_use_gecos_first_name_when_no_address_as_setting() -> None:
    info = user_info(None, "Nikhil Malhotra,,,", "nikhil")
    assert info.name == "Nikhil"
    assert info.address_as == "Nikhil"


def test_should_use_login_when_gecos_is_empty() -> None:
    info = user_info(None, "", "nikhil")
    assert info.name == "nikhil"
    assert info.address_as == ""


def test_should_use_default_user_when_nothing_is_known() -> None:
    info = user_info(None, "", "")
    assert info.name == "user"
    assert info.address_as == ""


def test_should_return_expected_os_label_when_platform_reports_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.release", lambda: "7.0.1")
    assert os_label() == "linux-7.0.1"


def test_should_build_envelope_with_fixed_inputs() -> None:
    now = datetime.datetime(2026, 10, 7, 9, 30, 15, tzinfo=datetime.UTC)
    environ = {"XDG_SESSION_TYPE": "x11", "LANG": "en_IN.UTF-8"}
    settings = Settings(brain=BrainSettings(address_as="Boss", max_steps=7))
    transcript = Transcript(text="x", engine="whisper.cpp/tiny.en", seconds=0.1)

    envelope = build_envelope(
        command="status",
        raw_transcript="hello",
        transcript=transcript,
        settings=settings,
        mode="balanced",
        now=now,
        environ=environ,
        turn_id="t1",
    )

    assert envelope.turn_id == "t1"
    assert envelope.command == "status"
    assert envelope.raw_transcript == "hello"
    assert envelope.stt.engine == "whisper.cpp/tiny.en"
    assert envelope.input_mode == "voice"
    assert envelope.context.display_server == "x11"
    assert envelope.context.locale == "en-IN"
    assert envelope.context.user.address_as == "Boss"
    assert envelope.policy.mode == "balanced"
    assert envelope.policy.max_steps == 7
    parsed_local_time = datetime.datetime.fromisoformat(envelope.context.local_time)
    assert parsed_local_time == now
    restored = TurnEnvelope.model_validate_json(envelope.to_json())
    assert restored == envelope


def test_should_generate_unique_default_turn_ids_when_no_turn_id_given() -> None:
    settings = Settings()
    transcript = Transcript(text="x", engine="whisper.cpp/tiny.en", seconds=0.1)
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z-[0-9a-f]{4}$")

    envelope_a = build_envelope(
        command="status",
        raw_transcript="hello",
        transcript=transcript,
        settings=settings,
        mode="balanced",
    )
    envelope_b = build_envelope(
        command="status",
        raw_transcript="hello",
        transcript=transcript,
        settings=settings,
        mode="balanced",
    )

    assert pattern.fullmatch(envelope_a.turn_id)
    assert pattern.fullmatch(envelope_b.turn_id)
    assert envelope_a.turn_id != envelope_b.turn_id


def test_should_make_a_sortable_utc_id_when_given_a_time() -> None:
    now = datetime.datetime(2026, 10, 7, 9, 30, 15, 123456, tzinfo=datetime.UTC)
    assert new_turn_id(now).startswith("2026-10-07T09:30:15.123Z-")


def test_should_carry_the_pending_question_into_the_context() -> None:
    transcript = Transcript(text="x", engine="whisper.cpp/tiny.en", seconds=0.1)
    envelope = build_envelope(
        command="the second one",
        raw_transcript="the second one",
        transcript=transcript,
        settings=Settings(),
        mode="balanced",
        pending_question="Which one?",
    )
    assert envelope.context.pending_question == "Which one?"
