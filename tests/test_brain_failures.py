"""Tests for jarvis.brain.failures response builders."""

import pytest

from jarvis.brain.failures import (
    ToolError,
    contract_fallback,
    internal_response,
    mcp_unavailable_response,
    process_exit_response,
    result_error_response,
    step_limit_response,
    timeout_response,
)
from jarvis.contract import FALLBACK_SPOKEN, sanitise_spoken


@pytest.mark.parametrize(
    ("result", "assistant_error", "why_fragment"),
    [
        ("Not logged in · Please run /login", "authentication_failed", "logged in"),
        ("Not logged in", None, "logged in"),
        ("", "authentication_failed", "logged in"),
        ("You've hit your usage limit", None, "limit"),
        ("anything", "rate_limit", "limit"),
        ("anything", "billing_error", "limit"),
        ("API Error: overloaded", None, "service"),
        ("x", "server_error", "service"),
        ("weird", None, "reported an error"),
    ],
)
def test_should_return_brain_unavailable_when_result_error_given(
    result: str, assistant_error: str | None, why_fragment: str
) -> None:
    response = result_error_response(result, assistant_error)
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "BRAIN_UNAVAILABLE"
    assert why_fragment in response.error.why
    assert response.error.remedy
    assert response.spoken.startswith("My AI brain isn't available")
    assert sanitise_spoken(response.spoken) == response.spoken


def test_should_return_timeout_when_timeout_given() -> None:
    response = timeout_response(120)
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "TIMEOUT"
    assert "120" in response.error.why
    assert "took too long" in response.spoken
    assert sanitise_spoken(response.spoken) == response.spoken


def test_should_return_brain_unavailable_when_process_exits() -> None:
    response = process_exit_response()
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "BRAIN_UNAVAILABLE"
    assert "stopped" in response.error.why
    assert sanitise_spoken(response.spoken) == response.spoken


def test_should_return_mcp_unavailable_when_mcp_missing() -> None:
    response = mcp_unavailable_response()
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "MCP_UNAVAILABLE"
    assert "tools" in response.spoken
    assert sanitise_spoken(response.spoken) == response.spoken


def test_should_return_internal_when_contract_fallback_used() -> None:
    response = contract_fallback()
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "INTERNAL"
    assert response.spoken == FALLBACK_SPOKEN
    assert sanitise_spoken(response.spoken) == response.spoken


def test_should_return_partial_when_step_limit_reached() -> None:
    response = step_limit_response(25)
    assert response.status == "partial"
    assert response.error is None
    assert "25" in response.spoken
    assert sanitise_spoken(response.spoken) == response.spoken


def test_should_carry_the_message_when_tool_error_is_raised() -> None:
    assert str(ToolError("boom")) == "boom"


def test_should_return_internal_when_the_session_hits_an_unexpected_error() -> None:
    response = internal_response()
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "INTERNAL"
    assert "unexpected" in response.error.why
    assert response.spoken == FALLBACK_SPOKEN
