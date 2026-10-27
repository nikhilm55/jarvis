"""Tests for jarvis.fastpath.responses."""

import datetime

import pytest

from jarvis.contract import ErrorInfo, FinalResponse, validate_response
from jarvis.desktop.client import DesktopError
from jarvis.fastpath import responses
from jarvis.policy import Mode


def error_of(response: FinalResponse) -> ErrorInfo:
    assert response.error is not None
    return response.error


def assert_contract_valid(response: FinalResponse) -> None:
    assert validate_response(response.model_dump()).spoken == response.spoken


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime.datetime(2026, 1, 1, 15, 42), "It's 3:42 PM."),
        (datetime.datetime(2026, 1, 1, 0, 5), "It's 12:05 AM."),
        (datetime.datetime(2026, 1, 1, 12, 0), "It's 12:00 PM."),
        (datetime.datetime(2026, 1, 1, 9, 7), "It's 9:07 AM."),
        (datetime.datetime(2026, 1, 1, 23, 59), "It's 11:59 PM."),
    ],
)
def test_should_return_formatted_time_when_given_datetime(
    now: datetime.datetime, expected: str
) -> None:
    assert responses.spoken_time(now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime.datetime(2026, 10, 7), "It's Wednesday, 7 October."),
        (datetime.datetime(2026, 1, 1), "It's Thursday, 1 January."),
        (datetime.datetime(2024, 2, 29), "It's Thursday, 29 February."),
    ],
)
def test_should_return_formatted_date_when_given_datetime(
    now: datetime.datetime, expected: str
) -> None:
    assert responses.spoken_date(now) == expected


def test_should_return_success_with_action_when_tool_present() -> None:
    resp = responses.ok("done", "calculator", "opened it", undoable=True)
    assert resp.status == "success"
    assert len(resp.actions_taken) == 1
    assert resp.actions_taken[0].undoable is True
    assert_contract_valid(resp)


def test_should_return_empty_actions_when_tool_is_none() -> None:
    resp = responses.ok("done", None)
    assert resp.status == "success"
    assert resp.actions_taken == []
    assert_contract_valid(resp)


def test_should_explain_balanced_mode_when_safe_mode_needs_confirmation() -> None:
    resp = responses.blocked("needs confirmation (M2)", "safe")
    assert resp.status == "failed"
    err = error_of(resp)
    assert err.code == "BLOCKED_BY_POLICY"
    assert err.why == "needs confirmation (M2)"
    assert "balanced" in err.remedy[0]
    assert "safe mode" in resp.spoken
    assert_contract_valid(resp)


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("balanced", "unknown tool"),
        ("safe", "policy error: audit unavailable"),
    ],
)
def test_should_not_blame_safe_mode_when_reason_is_not_a_confirmation(
    mode: Mode, reason: str
) -> None:
    resp = responses.blocked(reason, mode)
    assert resp.status == "failed"
    err = error_of(resp)
    assert err.code == "BLOCKED_BY_POLICY"
    assert err.why == reason
    assert "balanced" not in err.remedy[0]
    assert "safe mode" not in resp.spoken
    assert_contract_valid(resp)


def test_should_use_default_why_when_decision_reason_is_blank() -> None:
    resp = responses.blocked("   ", "safe")
    assert resp.status == "failed"
    err = error_of(resp)
    assert err.code == "BLOCKED_BY_POLICY"
    assert err.why == "no reason given"
    assert_contract_valid(resp)


@pytest.mark.parametrize(
    ("code", "expected_code"),
    [
        ("TIMEOUT", "TIMEOUT"),
        ("UNSUPPORTED_ON_PLATFORM", "UNSUPPORTED_ON_PLATFORM"),
        ("ELEVATED_WINDOW", "ELEVATED_WINDOW"),
        ("NOT_FOUND", "NOT_FOUND"),
        ("INTERNAL", "INTERNAL"),
        ("WEIRD", "INTERNAL"),
    ],
)
def test_should_map_error_code_when_desktop_failure(code: str, expected_code: str) -> None:
    exc = DesktopError(code, "something broke")
    resp = responses.desktop_failure("open Calculator", exc)
    assert resp.status == "failed"
    err = error_of(resp)
    assert err.code == expected_code
    assert resp.spoken.startswith("I couldn't open Calculator.")
    assert err.remedy
    assert err.why == "something broke"
    assert_contract_valid(resp)


def test_should_use_default_why_when_message_is_blank() -> None:
    exc = DesktopError("TIMEOUT", "")
    resp = responses.desktop_failure("open Calculator", exc)
    err = error_of(resp)
    assert err.why != ""


@pytest.mark.parametrize(
    ("result", "key", "default", "expected"),
    [
        ({"k": "val"}, "k", "d", "val"),
        ({}, "k", "d", "d"),
        ({"k": ""}, "k", "d", "d"),
        ({"k": "  "}, "k", "d", "d"),
        ({"k": 5}, "k", "d", "d"),
    ],
)
def test_should_return_text_or_default_when_value_invalid(
    result: dict[str, object], key: str, default: str, expected: str
) -> None:
    assert responses.text_of(result, key, default) == expected


@pytest.mark.parametrize(
    ("result", "default", "expected"),
    [
        ({"percent": 42}, 0, 42),
        ({}, 0, 0),
        ({"percent": "40"}, 0, 0),
        ({"percent": True}, 0, 0),
        ({"percent": 40.0}, 0, 0),
    ],
)
def test_should_return_percent_or_default_when_not_int(
    result: dict[str, object], default: int, expected: int
) -> None:
    assert responses.percent_of(result, default) == expected
