"""The run_shell gate: classification, scopes, consent and the YOLO guardrail (R84, §5.10)."""

import pytest

from jarvis import shell as _shell_policy
from jarvis.policy import Decision, ToolCall, TurnContext
from jarvis.policy.decide import decide
from tests.gated_rig import Confirmer, dispatch


def decision_for(cmd: str, mode: str) -> Decision:
    call = ToolCall("shell.run", {"cmd": cmd}, "brain")
    return decide(call, mode, TurnContext("t", mode=mode))  # type: ignore[arg-type]


def test_should_run_t0_commands_silently_in_balanced_mode() -> None:
    decision = decision_for("git log", "balanced")
    assert decision.action == "run"
    assert decision.scopes == ()


def test_should_confirm_before_a_normal_write_command_in_balanced_mode() -> None:
    decision = decision_for("mkdir -p demo && git init demo", "balanced")
    assert decision.action == "confirm"  # T2 without consent scopes: one voice confirmation
    assert decision.kind == "voice"


def test_should_ask_consent_for_paths_under_a_consent_folder() -> None:
    decision = decision_for("cat ~/Documents/report.md", "balanced")
    assert "files.documents:read" in decision.scopes
    assert decision.action == "consent"


def test_should_require_a_click_for_a_t3_command_in_balanced_mode() -> None:
    decision = decision_for("rm -rf ~", "balanced")
    assert decision.kind == "click"


def test_should_guardrail_a_t3_command_in_yolo_mode() -> None:
    decision = decision_for("rm -rf ~", "yolo")
    assert decision.kind == "guardrail"
    assert decision.tier is not None and decision.tier.name == "T3"


def test_should_fail_closed_on_an_unclassifiable_command() -> None:
    decision = decision_for(42, "balanced")  # type: ignore[arg-type]
    assert decision.tier is not None and decision.tier.name == "T3"


def test_should_confirm_a_fabricated_command_that_the_user_did_not_say() -> None:
    result, _, impl = dispatch(
        "shell.run",
        {"cmd": "git push origin main"},
        mode="yolo",
        heard=["push my changes"],
        confirmer=Confirmer(yes=True),
    )
    assert result.error is None  # "yes" confirmed it (R83)
    assert impl.calls


def test_should_refuse_the_fabricated_command_when_the_owner_says_no() -> None:
    result, _, impl = dispatch(
        "shell.run",
        {"cmd": "git push origin main"},
        mode="yolo",
        heard=["push my changes"],
        confirmer=Confirmer(yes=False),
    )
    assert result.error is not None and impl.calls == []


@pytest.mark.parametrize("mode", ["balanced", "yolo"])
def test_should_never_run_a_t3_command_without_its_click(mode: str) -> None:
    decision = decision_for("rm -rf ~", mode)
    assert decision.action != "run"
    assert _shell_policy.classify_shell("ls")[0].name == "T0"
