"""Tests for the Local model section requirement in the delegation guard hook."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from .git_env_utils import clean_git_env

HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"


def run_hook(name: str, payload: Mapping[str, object]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        env=clean_git_env(),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else {}


def decision(output: dict[str, object]) -> str:
    specific = output.get("hookSpecificOutput")
    return str(specific.get("permissionDecision")) if isinstance(specific, dict) else "allow"


FULL_BRIEF = """\
# Goal
Implement the feature.

# Context
Background information.

# Constraints
Keep it simple.

# Done when
Tests pass.

# Report
summary.json.

# Local model
Mode: loop
"""


def _payload(prompt: str, agent_type: str = "general-purpose") -> dict[str, object]:
    return {
        "tool_name": "Task",
        "tool_input": {"prompt": prompt, "subagent_type": agent_type},
        "hook_event_name": "PreToolUse",
    }


def test_should_allow_full_brief_with_loop_mode() -> None:
    output = run_hook("guard_delegation.py", _payload(FULL_BRIEF))
    assert decision(output) == "allow"


def test_should_allow_full_brief_with_finisher_mode() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "Mode: finisher")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "allow"


def test_should_allow_full_brief_with_review_mode() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "Mode: review")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "allow"


def test_should_allow_full_brief_with_exempt_reason() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "Mode: exempt: debugging a flaky timing test")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "allow"


def test_should_deny_brief_missing_local_model_section() -> None:
    brief = "\n".join(
        [
            "# Goal",
            "Implement the feature.",
            "",
            "# Context",
            "Background information.",
            "",
            "# Constraints",
            "Keep it simple.",
            "",
            "# Done when",
            "Tests pass.",
            "",
            "# Report",
            "summary.json.",
        ]
    )
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "deny"
    specific = output.get("hookSpecificOutput")
    reason = str(specific.get("permissionDecisionReason")) if isinstance(specific, dict) else ""
    assert "Local model" in reason


def test_should_deny_brief_with_invalid_mode() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "Mode: maybe")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "deny"


def test_should_deny_brief_with_exempt_no_reason() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "Mode: exempt:")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "deny"


def test_should_deny_brief_with_exempt_short_reason() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "Mode: exempt: tiny")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "deny"


def test_should_deny_brief_with_placeholder_local_model() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "TBD")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "deny"


def test_should_deny_brief_with_mode_in_code_fence_only() -> None:
    brief = FULL_BRIEF.replace("Mode: loop", "```\nMode: loop\n```")
    output = run_hook("guard_delegation.py", _payload(brief))
    assert decision(output) == "deny"


def test_should_allow_exempt_agent_without_brief() -> None:
    output = run_hook("guard_delegation.py", _payload("Find the audio module.", "Explore"))
    assert decision(output) == "allow"


@pytest.mark.parametrize(
    "mode",
    ["mode: loop", "**Mode:** finisher", "MODE: Review", "Mode: exempt: docs only change here"],
)
def test_should_allow_mode_lines_in_any_case_or_bold(mode: str) -> None:
    assert (
        decision(run_hook("guard_delegation.py", _payload(FULL_BRIEF.replace("Mode: loop", mode))))
        == "allow"
    )


@pytest.mark.parametrize("mode", ["Mode: loopy", "Mode: reviewed nothing", "finishers"])
def test_should_deny_words_that_only_start_like_a_mode(mode: str) -> None:
    assert (
        decision(run_hook("guard_delegation.py", _payload(FULL_BRIEF.replace("Mode: loop", mode))))
        == "deny"
    )
