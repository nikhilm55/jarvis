"""jarvis.request_access (FR-CON-03): one question up front for everything a task needs."""

import asyncio
from typing import Literal

import pytest

from jarvis.consent.request import MAX_SCOPES, REQUEST_ACCESS, requested_scopes
from jarvis.mcp.tools import TOOLS_BY_NAME
from jarvis.policy import Tier
from jarvis.policy.decision import TurnContext
from tests.gated_rig import Impl, clean_state, dispatch  # noqa: F401


class Consent:
    def __init__(self, result: Literal["granted", "denied"]) -> None:
        self.result = result
        self.asked: list[tuple[tuple[str, ...], str]] = []

    async def require(
        self, scopes: tuple[str, ...], reason: str, ctx: TurnContext
    ) -> Literal["granted", "denied"]:
        self.asked.append((scopes, reason))
        return self.result


def test_should_take_the_scopes_from_the_arguments_at_t0() -> None:
    tier, scopes = requested_scopes({"scopes": ["messages.teams:read", "calendar.google:*"]})
    assert tier == Tier.T0
    assert scopes == (
        "calendar.google:read",
        "calendar.google:write",
        "messages.teams:read",
    )


@pytest.mark.parametrize(
    "scopes",
    [None, "messages.teams:read", [], [1], ["NOPE"], ["a:delete"], ["x:read"] * (MAX_SCOPES + 1)],
)
def test_should_refuse_a_malformed_list(scopes: object) -> None:
    with pytest.raises(ValueError):
        requested_scopes({"scopes": scopes})


def test_should_ask_once_with_the_brains_reason_then_run() -> None:
    consent = Consent("granted")
    args = {"scopes": ["messages.teams:read", "messages.slack:read"], "reason": "read your unread"}
    result, _, impl = dispatch(REQUEST_ACCESS, args, mode="balanced", consent=consent)
    assert result.error is None and len(impl.calls) == 1
    assert consent.asked == [(("messages.slack:read", "messages.teams:read"), "read your unread")]


def test_should_refuse_with_consent_denied_when_the_user_says_no() -> None:
    consent = Consent("denied")
    args = {"scopes": ["messages.teams:read"], "reason": "x"}
    result, _, impl = dispatch(REQUEST_ACCESS, args, mode="balanced", consent=consent)
    assert result.error is not None and result.error.code == "CONSENT_DENIED"
    assert impl.calls == []
    assert "Jarvis, allow teams" in result.error.remedy[0]  # FR-CON-08


def test_should_not_ask_about_a_malformed_request() -> None:
    consent = Consent("granted")
    result, _, impl = dispatch(REQUEST_ACCESS, {"scopes": ["NOPE"]}, consent=consent)
    assert result.error is not None and consent.asked == [] and impl.calls == []


def test_should_cut_a_long_reason() -> None:
    consent = Consent("granted")
    args = {"scopes": ["screen:read"], "reason": "x" * 500}
    dispatch(REQUEST_ACCESS, args, mode="balanced", consent=consent)
    assert len(consent.asked[0][1]) == 120


def test_should_offer_it_to_the_brain() -> None:
    tool = TOOLS_BY_NAME["request_access"]
    assert tool.policy_name == REQUEST_ACCESS
    assert tool.input_schema["required"] == ["scopes", "reason"]


def test_should_answer_granted_once_the_gate_let_it_run() -> None:
    from jarvis.brain.clock import TurnClock  # noqa: PLC0415
    from jarvis.brain.dispatch import TurnHooks, TurnTools  # noqa: PLC0415

    async def say(text: str) -> None:
        return None

    async def ask(question: str, options: list[str]) -> str:
        return ""

    hooks = TurnHooks(say, ask, lambda final: None, TurnClock())
    tools = TurnTools("t1", hooks, object(), max_steps=5)  # type: ignore[arg-type]
    assert asyncio.run(tools(REQUEST_ACCESS, {"scopes": ["screen:read"]})) == "granted"
