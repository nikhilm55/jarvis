"""gated_dispatch asks the user: confirmation kinds, consent, and every way they say no."""

import pytest

from jarvis.policy import Tier
from jarvis.policy.ports import Answer, Method
from tests.gated_rig import Confirmer, Consent, clean_state, dispatch, records, tool  # noqa: F401


def test_should_run_when_the_user_confirms_and_audit_who_confirmed() -> None:
    tool("t.app", Tier.T2)
    confirmer = Confirmer(yes=True, method="button")
    result, ctx, impl = dispatch("t.app", mode="balanced", confirmer=confirmer)
    assert result.error is None
    assert len(impl.calls) == 1
    assert [(k, p) for p, k, _ in confirmer.asked] == [("voice", "Run t.app?")]
    assert records()[0]["confirmed_by"] == "button"
    assert ctx.policy_decisions[0].confirmed_by == "button"


@pytest.mark.parametrize(
    ("yes", "method", "code", "why"),
    [
        (False, "voice", "CANCELLED", "you declined"),
        (False, "timeout", "BLOCKED_BY_POLICY", "no answer to the confirmation"),
    ],
)
def test_should_refuse_when_the_user_says_no_or_does_not_answer(
    yes: bool, method: Method, code: str, why: str
) -> None:
    tool("t.app", Tier.T2)
    result, _, impl = dispatch("t.app", mode="balanced", confirmer=Confirmer(yes, method))
    assert result.error is not None
    assert (result.error.code, result.error.why) == (code, why)
    assert impl.calls == []


def test_should_ask_for_a_click_with_the_target_phrase_when_t3_in_yolo() -> None:
    tool("t.wipe", Tier.T3)
    confirmer = Confirmer(yes=True)
    dispatch("t.wipe", {"path": "/data/old-photos/"}, mode="yolo", confirmer=confirmer)
    assert [(k, phrase) for _, k, phrase in confirmer.asked] == [("guardrail", "old-photos")]
    confirmer = Confirmer(yes=True)
    dispatch("t.wipe", {"path": "/data/old-photos"}, mode="safe", confirmer=confirmer)
    assert [(k, phrase) for _, k, phrase in confirmer.asked] == [("click", None)]


def test_should_refuse_when_consent_is_denied_and_by_default() -> None:
    tool("t.files", Tier.T0, scopes=("files.documents:read",))
    result, _, impl = dispatch("t.files", mode="balanced")
    assert result.error is not None
    assert (result.error.code, result.error.why) == ("CONSENT_DENIED", "consent denied")
    consent = Consent("denied")
    result, _, impl2 = dispatch("t.files", mode="safe", consent=consent)
    assert result.error is not None
    assert consent.asked == [("files.documents:read",)]
    assert impl.calls == impl2.calls == []


def test_should_run_after_consent_and_ask_the_confirmation_that_is_still_due() -> None:
    tool("t.files", Tier.T1, scopes=("files.documents:read",))
    consent, confirmer = Consent("granted"), Confirmer(yes=True)
    result, _, impl = dispatch("t.files", mode="safe", consent=consent, confirmer=confirmer)
    assert result.error is None
    assert len(impl.calls) == 1
    assert len(confirmer.asked) == 1
    tool("t.files0", Tier.T0, scopes=("files.documents:read",))
    confirmer = Confirmer(yes=False)
    result, _, impl = dispatch("t.files0", mode="balanced", consent=consent, confirmer=confirmer)
    assert result.error is None
    assert confirmer.asked == []


def test_should_refuse_when_the_confirmer_itself_fails() -> None:
    class Broken:
        async def ask(self, *args: object, **kwargs: object) -> Answer:
            raise RuntimeError("hud gone")

    tool("t.app", Tier.T2)
    result, _, impl = dispatch("t.app", mode="balanced", confirmer=Broken())
    assert result.error is not None
    assert result.error.why == "policy error: RuntimeError"
    assert impl.calls == []
