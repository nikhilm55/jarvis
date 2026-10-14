"""Tests for the jarvis.policy safety gate."""

import json
from typing import Any

import pytest

from jarvis import paths, policy
from jarvis.policy import Mode, Tier, ToolSpec, gate, get, register

MODES: tuple[Mode, ...] = ("safe", "balanced", "yolo")


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "_REGISTRY", dict(policy._REGISTRY))


def _last_policy_record() -> dict[str, Any]:
    log = paths.data_dir() / "logs" / "jarvisd.jsonl"
    records: list[dict[str, Any]] = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
    ]
    for rec in reversed(records):
        if rec.get("name") == "jarvis.policy":
            return dict(rec)
    raise AssertionError("no policy log record found")


def test_should_deny_when_tool_unknown() -> None:
    d = gate("nope", {}, "safe")
    assert d.allowed is False
    assert d.reason == "unknown tool"


def test_should_deny_when_tool_not_str() -> None:
    d = gate(42, {}, "safe")  # type: ignore[arg-type]
    assert d.allowed is False
    assert d.reason == "unknown tool"


def test_should_deny_when_mode_unknown_even_for_t0() -> None:
    d = gate("desktop.volume_get", {}, "warp")  # type: ignore[arg-type]
    assert d.allowed is False
    assert d.reason == "unknown mode"


@pytest.mark.parametrize("mode", MODES)
def test_should_deny_when_scoped_t0_in_every_mode(mode: Mode) -> None:
    register(ToolSpec(name="scoped.tool", tier=Tier.T0, scopes=("file",)))
    d = gate("scoped.tool", {}, mode)
    assert d.allowed is False
    assert d.reason == "consent layer not built yet (M2)"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("tier", [Tier.T0, Tier.T1])
def test_should_allow_when_t0_or_t1_in_every_mode(mode: Mode, tier: Tier) -> None:
    name = f"tool.{tier.value}"
    register(ToolSpec(name=name, tier=tier))
    d = gate(name, {}, mode)
    assert d.allowed is True
    assert d.reason == f"allowed: {tier.value}"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("tier", [Tier.T2, Tier.T3])
def test_should_deny_when_t2_or_t3_in_every_mode(mode: Mode, tier: Tier) -> None:
    name = f"tool.{tier.value}"
    register(ToolSpec(name=name, tier=tier))
    d = gate(name, {}, mode)
    assert d.allowed is False
    assert "confirmation" in d.reason


def test_should_accept_duplicate_register_when_equal_spec() -> None:
    spec = ToolSpec(name="dup.tool", tier=Tier.T1)
    register(spec)
    register(spec)
    assert get("dup.tool") == spec


def test_should_raise_when_register_conflicts_and_keep_original() -> None:
    register(ToolSpec(name="conf.tool", tier=Tier.T1))
    with pytest.raises(ValueError, match="conflicting"):
        register(ToolSpec(name="conf.tool", tier=Tier.T2))
    spec = get("conf.tool")
    assert spec is not None
    assert spec.tier == Tier.T1


def test_should_return_spec_when_get_known() -> None:
    spec = ToolSpec(name="g.tool", tier=Tier.T0)
    register(spec)
    assert get("g.tool") == spec


def test_should_return_none_when_get_unknown() -> None:
    assert get("missing.tool") is None


def test_should_register_desktop_tools_with_exact_tiers() -> None:
    expected = {
        "desktop.open_app": Tier.T1,
        "desktop.close_app": Tier.T1,
        "desktop.volume_get": Tier.T0,
        "desktop.volume_set": Tier.T0,
        "desktop.volume_step": Tier.T0,
        "desktop.mute": Tier.T0,
    }
    for name, tier in expected.items():
        spec = get(name)
        assert spec is not None
        assert spec.tier == tier
        assert spec.scopes == ()


@pytest.mark.parametrize(
    "name",
    [
        "desktop.open_app",
        "desktop.close_app",
        "desktop.volume_get",
        "desktop.volume_set",
        "desktop.volume_step",
        "desktop.mute",
    ],
)
def test_should_allow_desktop_tools_when_balanced(name: str) -> None:
    d = gate(name, {}, "balanced")
    assert d.allowed is True


def test_should_not_mutate_args_when_gate_called() -> None:
    args: dict[str, object] = {"x": 1}
    gate("desktop.volume_get", args, "safe")
    assert args == {"x": 1}


def test_should_log_allow_decision_with_fields() -> None:
    gate("desktop.volume_get", {}, "balanced")
    rec = _last_policy_record()
    assert rec["tool"] == "desktop.volume_get"
    assert rec["tier"] == "T0"
    assert rec["mode"] == "balanced"
    assert rec["decision"] == "allow"


def test_should_log_deny_decision_with_fields() -> None:
    register(ToolSpec(name="t2.tool", tier=Tier.T2))
    gate("t2.tool", {}, "safe")
    rec = _last_policy_record()
    assert rec["tool"] == "t2.tool"
    assert rec["tier"] == "T2"
    assert rec["mode"] == "safe"
    assert rec["decision"] == "deny"


def test_should_log_unknown_tier_when_tool_unknown() -> None:
    gate("ghost.tool", {}, "safe")
    rec = _last_policy_record()
    assert rec["tool"] == "ghost.tool"
    assert rec["tier"] == "unknown"
    assert rec["decision"] == "deny"


def test_should_deny_when_tool_unhashable() -> None:
    d = gate(["desktop.volume_get"], {}, "safe")  # type: ignore[arg-type]
    assert d.allowed is False
    assert d.reason == "unknown tool"


@pytest.mark.parametrize(
    "name", ["Desktop.Volume_Get", " desktop.volume_get", "desktop.volume_get\n"]
)
def test_should_deny_when_tool_name_differs_only_by_case_or_whitespace(name: str) -> None:
    assert gate(name, {}, "yolo").allowed is False
