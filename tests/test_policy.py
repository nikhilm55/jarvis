"""Tests for the jarvis.policy safety gate."""

import errno
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from jarvis import log as jlog
from jarvis import paths
from jarvis.policy import Mode, Tier, ToolSpec, gate, get, legacy, register, registry

MODES: tuple[Mode, ...] = ("safe", "balanced", "yolo")


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


@pytest.fixture(autouse=True)
def clean_audit_handler() -> None:
    logger = logging.getLogger("jarvis.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.handlers.clear()
    logger.propagate = True


def _last_policy_record() -> dict[str, Any]:
    log = paths.data_dir() / "logs" / "audit.jsonl"
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
def test_should_allow_t0_in_every_mode(mode: Mode) -> None:
    name = "tool.T0"
    register(ToolSpec(name=name, tier=Tier.T0))
    d = gate(name, {}, mode)
    assert d.allowed is True
    assert d.reason == "allowed: T0"


@pytest.mark.parametrize("mode", ["balanced", "yolo"])
def test_should_allow_t1_when_balanced_or_yolo(mode: Mode) -> None:
    name = "tool.T1"
    register(ToolSpec(name=name, tier=Tier.T1))
    d = gate(name, {}, mode)
    assert d.allowed is True
    assert d.reason == "allowed: T1"


def test_should_deny_t1_when_safe_mode() -> None:
    name = "tool.T1"
    register(ToolSpec(name=name, tier=Tier.T1))
    d = gate(name, {}, "safe")
    assert d.allowed is False
    assert d.reason == "needs confirmation (M2)"
    rec = _last_policy_record()
    assert rec["decision"] == "deny"
    assert rec["tier"] == "T1"


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


def test_should_deny_open_and_close_app_when_safe() -> None:
    for name in ("desktop.open_app", "desktop.close_app"):
        d = gate(name, {}, "safe")
        assert d.allowed is False
    for name in (
        "desktop.volume_get",
        "desktop.volume_set",
        "desktop.volume_step",
        "desktop.mute",
    ):
        d = gate(name, {}, "safe")
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


def test_should_coerce_tier_string_when_valid() -> None:
    spec = ToolSpec("x.t", "T1")  # type: ignore[arg-type]
    assert spec.tier is Tier.T1
    register(spec)
    d_safe = gate("x.t", {}, "safe")
    assert d_safe.allowed is False
    assert d_safe.reason == "needs confirmation (M2)"
    d_balanced = gate("x.t", {}, "balanced")
    assert d_balanced.allowed is True


@pytest.mark.parametrize("bad_tier", ["T9", "t0", "", 0, None, 1.5])
def test_should_reject_invalid_tier(bad_tier: object) -> None:
    with pytest.raises(ValueError, match="tier"):
        ToolSpec("x.t", bad_tier)  # type: ignore[arg-type]


def test_should_coerce_scopes_list_to_tuple() -> None:
    spec = ToolSpec(name="s.tool", tier=Tier.T0, scopes=["a", "b"])  # type: ignore[arg-type]
    assert spec.scopes == ("a", "b")
    assert isinstance(spec.scopes, tuple)
    register(spec)
    d = gate("s.tool", {}, "safe")
    assert d.allowed is False
    assert d.reason == "consent layer not built yet (M2)"


@pytest.mark.parametrize("bad_scopes", ["file", 5, [1], ("a", 2), None])
def test_should_reject_invalid_scopes(bad_scopes: object) -> None:
    with pytest.raises(ValueError, match="scopes"):
        ToolSpec(name="s.tool", tier=Tier.T0, scopes=bad_scopes)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_name", ["", "  ", 5, None])
def test_should_reject_invalid_name(bad_name: object) -> None:
    with pytest.raises(ValueError, match="name"):
        ToolSpec(name=bad_name, tier=Tier.T0)  # type: ignore[arg-type]


def test_should_keep_valid_spec_equal_and_hashable() -> None:
    a = ToolSpec("n", Tier.T0)
    b = ToolSpec("n", "T0")  # type: ignore[arg-type]
    assert a == b
    assert hash(a) == hash(b)


def test_should_deny_when_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret-token-abc")

    monkeypatch.setattr(legacy, "audit", boom)
    d = gate("desktop.volume_get", {}, "yolo")
    assert d.allowed is False
    assert d.reason == "policy error: audit unavailable"
    assert "secret-token-abc" not in d.reason


def test_should_deny_when_log_dir_unwritable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(blocker / "home"))
    d = gate("desktop.volume_get", {}, "balanced")
    assert d.allowed is False
    assert d.reason == "policy error: audit unavailable"
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "ok"))
    d2 = gate("desktop.volume_get", {}, "balanced")
    assert d2.allowed is True


def test_should_deny_when_decision_logic_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(legacy, "_decide", boom)
    d = gate("desktop.volume_get", {}, "balanced")
    assert d.allowed is False
    assert d.reason == "policy error: ValueError"


@pytest.mark.parametrize("mode", MODES)
def test_should_deny_for_every_mode_when_audit_fails(
    mode: Mode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(legacy, "audit", boom)
    d = gate("desktop.volume_get", {}, mode)
    assert d.allowed is False
    assert d.reason == "policy error: audit unavailable"


def test_should_not_swallow_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(legacy, "audit", boom)
    with pytest.raises(KeyboardInterrupt):
        gate("desktop.volume_get", {}, "yolo")


class _BrokenStream:
    def write(self, data: str) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    def seek(self, offset: int, whence: int = 0) -> int:
        return 0

    def tell(self) -> int:
        return 0

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_should_deny_when_audit_write_hits_enospc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = gate("desktop.volume_get", {}, "yolo")
    assert d.allowed is True
    handler = jlog._audit_handler()
    monkeypatch.setattr(handler, "stream", _BrokenStream())
    d2 = gate("desktop.volume_get", {}, "yolo")
    assert d2.allowed is False
    assert d2.reason == "policy error: audit unavailable"


def test_should_deny_when_audit_rollover_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = gate("desktop.volume_get", {}, "yolo")
    assert d.allowed is True
    handler = jlog._audit_handler()

    def boom() -> None:
        raise OSError("rollover failed")

    monkeypatch.setattr(handler, "maxBytes", 1)
    monkeypatch.setattr(handler, "doRollover", boom)
    d2 = gate("desktop.volume_get", {}, "yolo")
    assert d2.allowed is False
    assert d2.reason == "policy error: audit unavailable"


def test_should_allow_and_record_when_audit_works() -> None:
    d = gate("desktop.volume_get", {}, "balanced")
    assert d.allowed is True
    rec = _last_policy_record()
    assert rec["decision"] == "allow"


def test_should_audit_even_when_logging_is_disabled() -> None:
    logging.disable(logging.CRITICAL)
    try:
        d = gate("desktop.volume_get", {}, "balanced")
        assert d.allowed is True
        rec = _last_policy_record()
        assert rec["decision"] == "allow"
    finally:
        logging.disable(logging.NOTSET)
