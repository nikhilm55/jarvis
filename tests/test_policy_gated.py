"""Tests for gated_dispatch: the one path to a tool (FR-SAFE-01, FR-SAFE-10)."""

import asyncio
from pathlib import Path

import pytest

from jarvis.config import PolicySettings
from jarvis.policy import Tier
from jarvis.policy import gated as gated_module
from jarvis.policy.decision import ToolCall, TurnContext
from jarvis.policy.gated import gated_dispatch
from jarvis.policy.ports import NEEDS_CONFIRMATION_REASON
from tests.gated_rig import Impl, clean_state, dispatch, records, tool  # noqa: F401


def test_should_run_the_tool_and_audit_decision_then_outcome_when_allowed() -> None:
    tool("t.read", Tier.T0)
    result, ctx, impl = dispatch("t.read", {"a": 1}, mode="balanced")
    assert (result.error, result.output) == (None, {"done": True})
    assert impl.calls == [{"a": 1}]
    decision, outcome = records()
    assert decision["msg"] == "policy decision"
    assert {k: decision[k] for k in ("turn_id", "tool", "tier", "mode", "decision")} == {
        "turn_id": "turn-1",
        "tool": "t.read",
        "tier": "T0",
        "mode": "balanced",
        "decision": "allow",
    }
    assert decision["confirmed_by"] is None
    assert (outcome["msg"], outcome["outcome"]) == ("tool outcome", "ok")
    assert [(r.tool, r.allowed, r.tier) for r in ctx.policy_decisions] == [("t.read", True, "T0")]


def test_should_write_the_audit_record_before_the_tool_runs() -> None:
    tool("t.read", Tier.T0)
    _, _, impl = dispatch("t.read", mode="yolo")
    assert [r["msg"] for r in impl.audit_at_call] == ["policy decision"]


def test_should_refuse_and_not_run_when_the_audit_log_is_unwritable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(gated_module, "audit", boom)
    tool("t.read", Tier.T0)
    result, ctx, impl = dispatch("t.read", mode="yolo")
    assert result.error is not None
    assert result.error.why == "policy error: audit unavailable"
    assert impl.calls == []
    assert [r.allowed for r in ctx.policy_decisions] == [False]


def test_should_refuse_with_the_deny_reason_when_the_tool_is_unknown() -> None:
    result, _, impl = dispatch("nope.tool", mode="yolo")
    assert result.error is not None
    assert (result.error.code, result.error.why) == ("BLOCKED_BY_POLICY", "unknown tool")
    assert impl.calls == []
    assert records()[0]["decision"] == "deny"


def test_should_refuse_a_deny_listed_path_even_in_yolo(tmp_path: Path) -> None:
    tool("t.read", Tier.T0)
    settings = PolicySettings(deny_paths=[str(tmp_path / "secret")])
    result, _, impl = dispatch(
        "t.read", {"path": str(tmp_path / "secret" / "k")}, mode="yolo", settings=settings
    )
    assert result.error is not None
    assert "deny list" in result.error.why
    assert impl.calls == []


def test_should_refuse_with_the_needs_confirmation_reason_when_nothing_can_ask() -> None:
    tool("t.app", Tier.T1)
    result, _, impl = dispatch("t.app", mode="safe")
    assert result.error is not None
    assert result.error.why == NEEDS_CONFIRMATION_REASON
    assert impl.calls == []


def test_should_audit_the_error_and_reraise_when_the_tool_fails() -> None:
    tool("t.read", Tier.T0)
    with pytest.raises(ValueError, match="bad"):
        dispatch("t.read", mode="yolo", impl=Impl(error=ValueError("bad")))
    assert records()[-1]["outcome"] == "error: ValueError"


def test_should_return_an_internal_error_when_no_implementation_is_registered() -> None:
    tool("t.read", Tier.T0)
    ctx = TurnContext("turn-1", mode="yolo")
    result = asyncio.run(gated_dispatch(ToolCall("t.read", {}, "internal"), ctx))
    assert result.error is not None
    assert result.error.code == "INTERNAL"


def test_should_list_every_decision_of_the_turn_in_order() -> None:
    tool("t.read", Tier.T0)
    tool("t.app", Tier.T1)
    ctx = TurnContext("turn-1", mode="safe", impls={"t.read": Impl(), "t.app": Impl()})
    for name in ("t.read", "t.app", "nope"):
        asyncio.run(gated_dispatch(ToolCall(name, {}, "fastpath"), ctx))
    got = [(r.tool, r.allowed) for r in ctx.policy_decisions]
    assert got == [("t.read", True), ("t.app", False), ("nope", False)]
    assert [r["tool"] for r in records() if r["msg"] == "policy decision"] == [
        "t.read",
        "t.app",
        "nope",
    ]
