"""Tests for fastpath gate reasons and volume step responses."""

import pytest

from jarvis import policy
from jarvis.contract import ErrorInfo, FinalResponse
from jarvis.fastpath import responses
from jarvis.fastpath.intents import VolumeStep
from jarvis.policy import registry
from tests.fastpath_fakes import FakeDesktop, allow_gate, run


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


def error_of(response: FinalResponse) -> ErrorInfo:
    assert response.error is not None
    return response.error


def test_should_expose_the_confirmation_reason_when_gate_denies_t1_in_safe_mode() -> None:
    policy.register(policy.ToolSpec("test.t1_tool", policy.Tier.T1))
    assert policy.gate("test.t1_tool", {}, "safe").reason == policy.NEEDS_CONFIRMATION_REASON


def test_should_give_balanced_remedy_when_reason_is_the_policy_confirmation_constant() -> None:
    decision = policy.Decision(False, policy.NEEDS_CONFIRMATION_REASON)
    response = responses.blocked(decision, "safe")
    assert "balanced" in error_of(response).remedy[0]
    assert "safe mode" in response.spoken


def test_should_not_give_balanced_remedy_when_a_t2_tool_is_denied_in_safe_mode() -> None:
    policy.register(policy.ToolSpec("test.t2_tool", policy.Tier.T2))
    decision = policy.gate("test.t2_tool", {}, "safe")
    assert not decision.allowed
    response = responses.blocked(decision, "safe")
    assert "balanced" not in error_of(response).remedy[0]
    assert "safe mode" not in response.spoken


@pytest.mark.parametrize(
    "reason",
    ["needs confirmation - M2", "needs confirmation (M2) extra", "Needs Confirmation (M2)"],
)
def test_should_not_give_balanced_remedy_when_reason_only_resembles_the_constant(
    reason: str,
) -> None:
    response = responses.blocked(policy.Decision(False, reason), "safe")
    assert "balanced" not in error_of(response).remedy[0]
    assert "safe mode" not in response.spoken


def test_should_speak_a_neutral_line_when_volume_step_result_has_no_percent() -> None:
    events: list[str] = []
    desktop = FakeDesktop(events, results={"volume_step": {"muted": False}})
    response = run(VolumeStep(10), desktop, "balanced", gate=allow_gate(events))
    assert response.status == "success"
    assert response.spoken == "Volume changed."
    assert response.actions_taken[0].tool == "desktop.volume_step"


def test_should_speak_the_percent_when_volume_step_result_has_it() -> None:
    events: list[str] = []
    desktop = FakeDesktop(events, results={"volume_step": {"percent": 50, "muted": False}})
    response = run(VolumeStep(10), desktop, "balanced", gate=allow_gate(events))
    assert response.spoken == "Volume 50 percent."
