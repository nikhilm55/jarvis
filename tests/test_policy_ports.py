"""The gate's ports fail closed: with nothing plugged in, nothing needs-asking runs."""

import asyncio

from jarvis.policy.decision import TurnContext
from jarvis.policy.ports import Answer, NoConfirmer, NoConsent


def test_should_answer_no_when_nothing_can_ask_the_user() -> None:
    answer = asyncio.run(NoConfirmer().ask("Run it?", "voice"))
    assert answer == Answer(False, "timeout")


def test_should_deny_consent_when_no_broker_is_plugged_in() -> None:
    ctx = TurnContext("t1")
    assert asyncio.run(NoConsent().require(("files.documents:read",), "why", ctx)) == "denied"


def test_should_default_a_turn_to_safe_mode_with_the_refusing_ports() -> None:
    ctx = TurnContext("t1")
    assert ctx.mode == "safe"
    assert isinstance(ctx.confirmer, NoConfirmer)
    assert isinstance(ctx.consent, NoConsent)
    assert ctx.policy_decisions == []
    assert ctx.impls == {}
    assert TurnContext("t2").policy_decisions is not ctx.policy_decisions
