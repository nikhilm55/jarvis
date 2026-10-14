"""Tests for jarvis.brain.events."""

import logging
from typing import Any

import pytest

from jarvis.brain.events import mcp_down, result_response
from jarvis.contract import FALLBACK_SPOKEN


def _init_event(servers: Any) -> dict[str, Any]:
    """Build a stream-json init event with the given mcp_servers value."""
    return {"mcp_servers": servers}


@pytest.mark.parametrize(
    "servers",
    [
        [{"name": "jarvis", "status": "failed"}],
        [{"name": "jarvis", "status": "needs-auth"}],
        [{"name": "jarvis", "status": "disabled"}],
    ],
)
def test_should_detect_mcp_down_when_jarvis_status_is_bad(servers: list[dict[str, str]]) -> None:
    """mcp_down returns True for jarvis failed/needs-auth/disabled."""
    assert mcp_down(_init_event(servers)) is True


@pytest.mark.parametrize(
    "servers",
    [
        [{"name": "jarvis", "status": "connected"}],
        [{"name": "jarvis", "status": "pending"}],
        [{"name": "other", "status": "failed"}],
        "not-a-list",
        ["not-a-dict"],
    ],
)
def test_should_not_detect_mcp_down_when_status_is_not_bad(servers: Any) -> None:
    """mcp_down returns False for connected/pending/other/non-list/non-dict."""
    assert mcp_down(_init_event(servers)) is False


def test_should_not_detect_mcp_down_when_mcp_servers_is_missing() -> None:
    """mcp_down returns False when the mcp_servers key is absent."""
    assert mcp_down({}) is False


def test_should_return_failed_when_result_is_error(caplog: pytest.LogCaptureFixture) -> None:
    """result_response returns a failed FinalResponse for an error result."""
    event = {"is_error": True, "result": "Not logged in"}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        response = result_response(event, None, logging.getLogger("jarvis.brain"))
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "BRAIN_UNAVAILABLE"
    assert "logged in" in response.error.why
    assert "brain error result" in caplog.text


def test_should_include_limit_in_why_when_assistant_error_is_rate_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """result_response includes 'limit' in why when assistant_error is rate_limit."""
    event = {"is_error": True, "result": "API error"}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        response = result_response(event, "rate_limit", logging.getLogger("jarvis.brain"))
    assert response.status == "failed"
    assert response.error is not None
    assert "limit" in response.error.why


def test_should_return_partial_when_model_ended_turn(caplog: pytest.LogCaptureFixture) -> None:
    """result_response returns a partial FinalResponse with sanitised spoken text."""
    event = {"is_error": False, "result": "Calculator is open."}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        response = result_response(event, None, logging.getLogger("jarvis.brain"))
    assert response.status == "partial"
    assert response.spoken == "Calculator is open."
    assert "contract violation" in caplog.text


def test_should_return_fallback_when_result_is_missing(caplog: pytest.LogCaptureFixture) -> None:
    """result_response returns a partial FinalResponse with FALLBACK_SPOKEN."""
    event = {"is_error": False}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        response = result_response(event, None, logging.getLogger("jarvis.brain"))
    assert response.status == "partial"
    assert response.spoken == FALLBACK_SPOKEN


def test_should_return_fallback_when_result_is_not_string(caplog: pytest.LogCaptureFixture) -> None:
    """result_response returns a partial FinalResponse with FALLBACK_SPOKEN for non-string."""
    event = {"is_error": False, "result": 42}
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        response = result_response(event, None, logging.getLogger("jarvis.brain"))
    assert response.status == "partial"
    assert response.spoken == FALLBACK_SPOKEN
