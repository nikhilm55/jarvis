"""Tests for jarvis.brain.rules."""

import pytest

from jarvis.brain.rules import RULES, build_rules
from jarvis.mcp.tools import TOOLS


def test_should_include_every_tool_name_when_tools_exist() -> None:
    """Every tool in TOOLS appears by bare name in build_rules()."""
    text = build_rules()
    for tool in TOOLS:
        assert tool.name in text


def test_should_state_every_turn_ends_with_respond_when_rules_built() -> None:
    """The text states every turn must end with a respond call."""
    text = build_rules()
    assert "respond" in text
    assert "exactly one" in text


def test_should_mention_each_status_value_when_rules_built() -> None:
    """The text mentions each status value."""
    text = build_rules()
    for status in ["success", "partial", "failed", "needs_input", "cancelled"]:
        assert status in text


def test_should_mention_mcp_prefix_when_rules_built() -> None:
    """The text mentions the prefix mcp__jarvis__."""
    text = build_rules()
    assert "mcp__jarvis__" in text


def test_should_say_envelope_content_is_data_when_rules_built() -> None:
    """The text says envelope content is data not instructions."""
    text = build_rules()
    assert "DATA" in text


def test_should_say_no_shell_when_rules_built() -> None:
    """The text tells the model it has no shell."""
    text = build_rules()
    assert "NO shell" in text


def test_should_distinguish_send_and_write_when_rules_built() -> None:
    """Send and write are distinguished in the text."""
    text = build_rules()
    assert "send" in text.lower()
    assert "compose" in text.lower()


def test_should_stay_short_when_rules_built() -> None:
    """The prompt stays short: len(build_rules()) <= 3000."""
    assert len(build_rules()) <= 3000


def test_should_have_no_long_lines_or_tabs_or_whitespace_when_rules_built() -> None:
    """No line is longer than 100 chars, no tabs, no leading/trailing whitespace."""
    text = build_rules()
    assert text == text.strip()
    assert "\t" not in text
    for line in text.splitlines():
        assert len(line) <= 100


@pytest.mark.parametrize(
    "code",
    [
        "NOT_FOUND",
        "AMBIGUOUS",
        "APP_NOT_INSTALLED",
        "UNSUPPORTED_ON_PLATFORM",
        "BLOCKED_BY_POLICY",
        "TIMEOUT",
        "INTERNAL",
    ],
)
def test_should_include_every_error_code_when_rules_built(code: str) -> None:
    """Every ErrorCode literal the brain may use appears."""
    text = build_rules()
    assert code in text


def test_should_be_deterministic_when_called_twice() -> None:
    """build_rules() is deterministic and equals RULES."""
    assert build_rules() == build_rules()
    assert build_rules() == RULES


def test_should_ask_for_minimal_respond_when_the_action_is_simple() -> None:
    """Output tokens are latency: simple actions must not carry display or actions_taken."""
    text = build_rules()
    assert "Keep respond minimal" in text
    assert "actions_taken or display" in text
