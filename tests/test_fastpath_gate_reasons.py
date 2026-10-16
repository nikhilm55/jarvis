"""Tests for fastpath gate reasons and volume step responses."""

import asyncio
from collections.abc import Mapping

import pytest

from jarvis import policy
from jarvis.contract import ErrorInfo, FinalResponse
from jarvis.fastpath import responses
from jarvis.fastpath.intents import Intent, Mute, OpenApp, VolumeSet, VolumeStep
from jarvis.policy import registry
from jarvis.policy.decision import Kind, ToolCall, TurnContext
from jarvis.policy.gated import gated_dispatch
from jarvis.policy.ports import Answer, Method
from tests.fastpath_fakes import FakeDesktop, run


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


def error_of(response: FinalResponse) -> ErrorInfo:
    assert response.error is not None
    return response.error


def refusal(tier: policy.Tier) -> ErrorInfo:
    policy.register(policy.ToolSpec("test.tool", tier))
    ctx = TurnContext("t1", mode="safe", impls={"test.tool": Impl()})
    result = asyncio.run(gated_dispatch(ToolCall("test.tool", {}, "fastpath"), ctx))
    assert result.error is not None
    return result.error


class Impl:
    tool_name = "test.tool"

    async def __call__(self, args: Mapping[str, object]) -> object:
        return {}


def test_should_expose_the_confirmation_reason_when_the_gate_refuses_t1_in_safe_mode() -> None:
    assert refusal(policy.Tier.T1).why == policy.NEEDS_CONFIRMATION_REASON


def test_should_give_balanced_remedy_when_reason_is_the_policy_confirmation_constant() -> None:
    response = responses.blocked(policy.NEEDS_CONFIRMATION_REASON, "safe")
    assert "balanced" in error_of(response).remedy[0]
    assert "safe mode" in response.spoken


@pytest.mark.parametrize("tier", [policy.Tier.T2, policy.Tier.T3])
def test_should_not_give_balanced_remedy_when_a_t2_or_t3_tool_is_refused_in_safe_mode(
    tier: policy.Tier,
) -> None:
    reason = refusal(tier).why
    assert reason != policy.NEEDS_CONFIRMATION_REASON
    response = responses.blocked(reason, "safe")
    assert "balanced" not in error_of(response).remedy[0]
    assert "safe mode" not in response.spoken


@pytest.mark.parametrize(
    "reason",
    ["needs confirmation - M2", "needs confirmation (M2) extra", "Needs Confirmation (M2)"],
)
def test_should_not_give_balanced_remedy_when_reason_only_resembles_the_constant(
    reason: str,
) -> None:
    response = responses.blocked(reason, "safe")
    assert "balanced" not in error_of(response).remedy[0]
    assert "safe mode" not in response.spoken


def test_should_speak_a_neutral_line_when_volume_step_result_has_no_percent() -> None:
    events: list[str] = []
    desktop = FakeDesktop(events, results={"volume_step": {"muted": False}})
    response = run(VolumeStep(10), desktop, "balanced")
    assert response.status == "success"
    assert response.spoken == "Volume changed."
    assert response.actions_taken[0].tool == "desktop.volume_step"


def test_should_speak_the_percent_when_volume_step_result_has_it() -> None:
    events: list[str] = []
    desktop = FakeDesktop(events, results={"volume_step": {"percent": 50, "muted": False}})
    response = run(VolumeStep(10), desktop, "balanced")
    assert response.spoken == "Volume 50 percent."


@pytest.mark.parametrize("intent", [VolumeSet(40), VolumeStep(10), Mute(True)])
def test_should_confirm_changing_the_volume_in_safe_mode_and_run_it_in_balanced(
    intent: Intent,
) -> None:
    events: list[str] = []
    safe = run(intent, FakeDesktop(events), "safe")
    assert error_of(safe).code == "BLOCKED_BY_POLICY"
    assert "balanced" in error_of(safe).remedy[0]
    assert events == []
    assert run(intent, FakeDesktop(events), "balanced").status == "success"


@pytest.mark.parametrize(
    ("yes", "method", "code"),
    [(False, "voice", "CANCELLED"), (False, "timeout", "BLOCKED_BY_POLICY")],
)
def test_should_keep_the_gates_error_code_when_the_user_declines_or_does_not_answer(
    yes: bool, method: Method, code: str
) -> None:
    events: list[str] = []
    ctx = TurnContext("t1", confirmer=AskedOnce(Answer(yes, method)))
    response = run(OpenApp("Calculator"), FakeDesktop(events), "safe", ctx=ctx)
    assert error_of(response).code == code
    assert events == []


def test_should_run_the_intent_when_the_user_confirms_in_safe_mode() -> None:
    events: list[str] = []
    ctx = TurnContext("t1", confirmer=AskedOnce(Answer(True, "voice")))
    response = run(OpenApp("Calculator"), FakeDesktop(events), "safe", ctx=ctx)
    assert response.status == "success"
    assert events == ["desktop.open_app"]
    assert ctx.policy_decisions[0].confirmed_by == "voice"


class AskedOnce:
    def __init__(self, answer: Answer) -> None:
        self.answer = answer

    async def ask(
        self, prompt: str, kind: Kind, target_phrase: str | None = None, timeout_s: float = 15
    ) -> Answer:
        return self.answer
