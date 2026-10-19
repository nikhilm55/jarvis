"""C1 and I1: "never" beats every mode at every tier, and no grant exists without its audit."""

import asyncio
from pathlib import Path

import pytest

from jarvis.consent.scope import Scope
from jarvis.policy import Tier
from jarvis.policy import gated as gated_module
from jarvis.policy.decision import Decision, ToolCall, TurnContext
from jarvis.policy.gated import ToolResult, gated_dispatch
from tests.consent_rig import TEAMS_R, Rig, make_rig, says
from tests.gated_rig import Confirmer, Impl, clean_state, records, tool  # noqa: F401

NEVER = TEAMS_R
MALFORMED = "not-a-valid-scope"


def _through_broker(
    rig: Rig, name: str, mode: str, confirmer: Confirmer | None = None
) -> tuple[ToolResult, Impl]:
    """Dispatch `name` through the real gate with the rig's real broker as the consent port."""
    impl = Impl(name)
    fields = {"confirmer": confirmer} if confirmer else {}
    ctx = TurnContext("turn-1", mode=mode, consent=rig.broker, impls={name: impl}, **fields)  # type: ignore[arg-type]
    return asyncio.run(gated_dispatch(ToolCall(name, {}, "brain"), ctx)), impl


@pytest.mark.parametrize("scope", [NEVER, MALFORMED], ids=["never", "malformed"])
@pytest.mark.parametrize("tier", list(Tier), ids=lambda t: t.value)
@pytest.mark.parametrize("mode", ["safe", "balanced", "yolo"])
def test_should_refuse_a_never_or_malformed_scope_in_every_mode_and_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, tier: Tier, scope: str
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("session"))
    rig.store.grant(Scope.parse(NEVER), "never", "voice")
    tool("t.scoped", tier, scopes=(scope,))
    result, impl = _through_broker(rig, "t.scoped", mode, Confirmer(yes=True))
    assert result.error is not None
    assert result.error.code == "CONSENT_DENIED"
    assert impl.calls == []
    assert len(rig.checks()) == 1  # the broker was consulted, before any confirmation
    assert rig.asker.asked == []  # and refused without asking: "never" is final


def test_should_run_a_yolo_t3_tool_once_its_scope_is_granted_and_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch)
    tool("t.wipe", Tier.T3, scopes=(TEAMS_R,))
    confirmer = Confirmer(yes=True)
    result, impl = _through_broker(rig, "t.wipe", "yolo", confirmer)
    assert result.error is None
    assert len(impl.calls) == 1
    assert len(rig.checks()) == 1  # consulted once; YOLO auto-allows the scope
    assert len(confirmer.asked) == 1  # the guardrail confirmation still follows


def test_should_deny_an_allowed_verdict_with_scopes_that_has_no_consent_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool("t.scoped", Tier.T1, scopes=(TEAMS_R,))
    decision = Decision("run", Tier.T1, (TEAMS_R,), reason="allowed")

    async def unchecked(call: ToolCall, ctx: TurnContext) -> gated_module._Verdict:
        return gated_module._Verdict(True, decision, "allowed")  # skipped the broker

    monkeypatch.setattr(gated_module, "_judge", unchecked)
    impl = Impl("t.scoped")
    ctx = TurnContext("turn-1", impls={"t.scoped": impl})
    result = asyncio.run(gated_dispatch(ToolCall("t.scoped", {}, "brain"), ctx))
    assert result.error is not None
    assert result.error.why == "policy error: RuntimeError"
    assert impl.calls == []


@pytest.mark.parametrize("choice", ["once", "session", "always", "never"])
def test_should_ask_again_after_an_answer_audit_failed_and_hold_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says(choice))  # type: ignore[arg-type]
    audited = rig.broker._audit

    def failing(ctx: TurnContext, scopes: tuple[str, ...], message: str, outcome: object) -> None:
        if message == "consent answer":
            raise OSError("audit log unwritable")
        audited(ctx, scopes, message, outcome)  # type: ignore[arg-type]

    monkeypatch.setattr(rig.broker, "_audit", failing)
    assert rig.require(TEAMS_R) == "denied"
    assert rig.store.get(Scope.parse(TEAMS_R)) is None  # no always or never was stored
    monkeypatch.setattr(rig.broker, "_audit", audited)
    rig.require(TEAMS_R, turn="t1")  # same turn: a once or session grant would answer silently
    assert len(rig.asker.asked) == 2  # the first answer left nothing behind, so it asks again
