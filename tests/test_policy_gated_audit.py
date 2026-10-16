"""The audit rule of M1, kept: no allow without a written audit record (FR-SAFE-10)."""

import errno
import logging
from pathlib import Path

import pytest

from jarvis import log as jlog
from jarvis.policy import Tier
from jarvis.policy import gated as gated_module
from tests.gated_rig import clean_state, dispatch, records, tool  # noqa: F401


class BrokenStream:
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


def refused_for_audit(result_error: object) -> bool:
    return getattr(result_error, "why", None) == "policy error: audit unavailable"


def test_should_log_a_deny_with_the_tier_and_an_unknown_tool_with_tier_unknown() -> None:
    tool("t2.tool", Tier.T2)
    dispatch("t2.tool", mode="safe")
    dispatch("ghost.tool", mode="safe")
    t2, ghost = records()
    assert (t2["tool"], t2["tier"], t2["mode"], t2["decision"]) == ("t2.tool", "T2", "safe", "deny")
    assert (ghost["tool"], ghost["tier"], ghost["decision"]) == ("ghost.tool", "unknown", "deny")


def test_should_refuse_without_leaking_the_error_when_the_audit_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret-token-abc")

    monkeypatch.setattr(gated_module, "audit", boom)
    tool("t.read", Tier.T0)
    result, _, impl = dispatch("t.read", mode="yolo")
    assert refused_for_audit(result.error)
    assert "secret-token-abc" not in str(result.error)
    assert impl.calls == []


def test_should_refuse_when_the_log_dir_is_unwritable_and_recover_when_it_is_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    tool("t.read", Tier.T0)
    monkeypatch.setenv("JARVIS_HOME", str(blocker / "home"))
    result, _, impl = dispatch("t.read", mode="balanced")
    assert refused_for_audit(result.error)
    assert impl.calls == []
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "ok"))
    result, _, impl = dispatch("t.read", mode="balanced")
    assert result.error is None
    assert len(impl.calls) == 1


def test_should_refuse_when_the_audit_write_hits_enospc(monkeypatch: pytest.MonkeyPatch) -> None:
    tool("t.read", Tier.T0)
    assert dispatch("t.read", mode="yolo")[0].error is None
    monkeypatch.setattr(jlog._audit_handler(), "stream", BrokenStream())
    result, _, impl = dispatch("t.read", mode="yolo")
    assert refused_for_audit(result.error)
    assert impl.calls == []


def test_should_refuse_when_the_audit_rollover_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise OSError("rollover failed")

    tool("t.read", Tier.T0)
    assert dispatch("t.read", mode="yolo")[0].error is None
    handler = jlog._audit_handler()
    monkeypatch.setattr(handler, "maxBytes", 1)
    monkeypatch.setattr(handler, "doRollover", boom)
    result, _, impl = dispatch("t.read", mode="yolo")
    assert refused_for_audit(result.error)
    assert impl.calls == []


def test_should_audit_even_when_logging_is_disabled() -> None:
    tool("t.read", Tier.T0)
    logging.disable(logging.CRITICAL)
    try:
        result, _, _ = dispatch("t.read", mode="balanced")
        assert result.error is None
        assert records()[0]["decision"] == "allow"
    finally:
        logging.disable(logging.NOTSET)


def test_should_not_swallow_a_keyboard_interrupt_from_the_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(gated_module, "audit", boom)
    tool("t.read", Tier.T0)
    with pytest.raises(KeyboardInterrupt):
        dispatch("t.read", mode="yolo")
