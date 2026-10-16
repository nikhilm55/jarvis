"""Tests for the policy `decide` function (FRS 5.10 mode table)."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from jarvis.config import PolicySettings
from jarvis.policy import registry
from jarvis.policy.decide import decide
from jarvis.policy.decision import ToolCall, TurnContext
from jarvis.policy.model import Mode, Tier, ToolSpec


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the registry so registrations do not leak between tests."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


def _ctx(settings: PolicySettings | None = None) -> TurnContext:
    return TurnContext("t1", settings=settings or PolicySettings())


def _call(name: str, args: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(name=name, args=args or {}, origin="brain")


TABLE: list[tuple[Mode, Tier, str, str | None]] = [
    ("safe", Tier.T0, "run", None),
    ("safe", Tier.T1, "confirm", "voice"),
    ("safe", Tier.T2, "confirm", "voice"),
    ("safe", Tier.T3, "confirm", "click"),
    ("balanced", Tier.T0, "run", None),
    ("balanced", Tier.T1, "run", None),
    ("balanced", Tier.T2, "confirm", "voice"),
    ("balanced", Tier.T3, "confirm", "click"),
    ("yolo", Tier.T0, "run", None),
    ("yolo", Tier.T1, "run", None),
    ("yolo", Tier.T2, "run", None),
    ("yolo", Tier.T3, "confirm", "guardrail"),
]


@pytest.mark.parametrize("mode,tier,action,kind", TABLE)
def test_table_cells(mode: Mode, tier: Tier, action: str, kind: str | None) -> None:
    """Every (mode, tier) cell of the FRS 5.10 table produces the right action/kind."""
    registry.register(ToolSpec("t.tier", tier))
    call = _call("t.tier")
    decision = decide(call, mode, _ctx())
    assert decision.action == action
    assert decision.kind == kind
    assert decision.tier == tier


def test_unknown_mode_denies() -> None:
    registry.register(ToolSpec("t.tier", Tier.T0))
    call = _call("t.tier")
    decision = decide(call, "bogus", _ctx())  # type: ignore[arg-type]
    assert decision.action == "deny"
    assert decision.tier is None
    assert decision.reason == "unknown mode"


def test_unknown_tool_denies() -> None:
    call = _call("no.such.tool")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "deny"
    assert decision.tier is None
    assert decision.reason == "unknown tool"


def test_non_str_name_denies() -> None:
    call = ToolCall(name=42, args={}, origin="brain")  # type: ignore[arg-type]
    decision = decide(call, "safe", _ctx())
    assert decision.action == "deny"
    assert decision.tier is None
    assert decision.reason == "unknown tool"


def test_classifier_raises_tier() -> None:
    def classify(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
        return (Tier.T3, ())

    registry.register(ToolSpec("t.classify", Tier.T1, classify=classify))
    call = _call("t.classify")
    decision = decide(call, "safe", _ctx())
    assert decision.tier == Tier.T3
    assert decision.action == "confirm"
    assert decision.kind == "click"


def test_classifier_cannot_lower_tier() -> None:
    def classify(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
        return (Tier.T0, ())

    registry.register(ToolSpec("t.classify", Tier.T3, classify=classify))
    call = _call("t.classify")
    decision = decide(call, "safe", _ctx())
    assert decision.tier == Tier.T3
    assert decision.action == "confirm"
    assert decision.kind == "click"


def test_classifier_scopes_merged_sorted() -> None:
    def classify(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
        return (Tier.T1, ("z.scope", "a.scope"))

    registry.register(ToolSpec("t.classify", Tier.T1, scopes=("m.scope",), classify=classify))
    call = _call("t.classify")
    decision = decide(call, "safe", _ctx())
    assert decision.scopes == ("a.scope", "m.scope", "z.scope")


def test_classifier_raises_exception_denies() -> None:
    def classify(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
        raise RuntimeError("boom")

    registry.register(ToolSpec("t.classify", Tier.T1, classify=classify))
    call = _call("t.classify")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "deny"
    assert decision.tier is None
    assert decision.reason == "policy error: RuntimeError"


def test_deny_path_denies_in_every_mode(tmp_path: Path) -> None:
    secret = str(tmp_path / "secret")
    settings = PolicySettings(deny_paths=[secret])
    registry.register(ToolSpec("t.deny", Tier.T0))
    call = _call("t.deny", {"path": str(tmp_path / "secret" / "k")})
    for mode in ("safe", "balanced", "yolo"):
        decision = decide(call, mode, _ctx(settings))
        assert decision.action == "deny"
        assert decision.tier == Tier.T0
        assert "deny list" in decision.reason


def test_deny_command_regex_denies() -> None:
    settings = PolicySettings(deny_commands=[r"^rm\b"])
    registry.register(ToolSpec("t.shell", Tier.T0))
    call = _call("t.shell", {"cmd": "rm -rf /"})
    decision = decide(call, "yolo", _ctx(settings))
    assert decision.action == "deny"
    assert decision.tier == Tier.T0
    assert "deny list" in decision.reason


def test_path_outside_deny_list_not_denied(tmp_path: Path) -> None:
    settings = PolicySettings(deny_paths=[str(tmp_path / "secret")])
    registry.register(ToolSpec("t.deny", Tier.T0))
    call = _call("t.deny", {"path": str(tmp_path / "other" / "file")})
    decision = decide(call, "safe", _ctx(settings))
    assert decision.action == "run"


def test_symlink_into_denied_path_denied(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "k").write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(secret)
    settings = PolicySettings(deny_paths=[str(secret)])
    registry.register(ToolSpec("t.deny", Tier.T0))
    call = _call("t.deny", {"path": str(link / "k")})
    decision = decide(call, "safe", _ctx(settings))
    assert decision.action == "deny"
    assert "deny list" in decision.reason


def test_allow_list_does_not_lower_tier(tmp_path: Path) -> None:
    path = str(tmp_path / "doc.txt")
    settings = PolicySettings(allow_paths=[path])
    registry.register(ToolSpec("t.allow", Tier.T2))
    call = _call("t.allow", {"path": path})
    decision = decide(call, "balanced", _ctx(settings))
    assert decision.action == "confirm"
    assert decision.tier == Tier.T2


def test_scopes_consent_safe_balanced() -> None:
    registry.register(ToolSpec("t.scopes", Tier.T1, scopes=("files.documents:read",)))
    call = _call("t.scopes")
    for mode in ("safe", "balanced"):
        decision = decide(call, mode, _ctx())
        assert decision.action == "consent"
        assert decision.scopes == ("files.documents:read",)


def test_t1_safe_consent_then_confirm_voice() -> None:
    registry.register(ToolSpec("t.scopes", Tier.T1, scopes=("files.documents:read",)))
    call = _call("t.scopes")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "consent"
    assert decision.then_confirm == "voice"


def test_t0_balanced_consent_then_confirm_none() -> None:
    registry.register(ToolSpec("t.scopes", Tier.T0, scopes=("files.documents:read",)))
    call = _call("t.scopes")
    decision = decide(call, "balanced", _ctx())
    assert decision.action == "consent"
    assert decision.then_confirm is None


def test_yolo_scopes_run_auto_allowed() -> None:
    registry.register(ToolSpec("t.scopes", Tier.T1, scopes=("files.documents:read",)))
    call = _call("t.scopes")
    decision = decide(call, "yolo", _ctx())
    assert decision.action == "run"
    assert decision.reason == "auto-allowed: YOLO"


def test_path_scopes_write_for_t1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # where Windows looks for home
    docs = tmp_path / "Documents"
    docs.mkdir()
    target = docs / "note.txt"
    target.write_text("x", encoding="utf-8")
    registry.register(ToolSpec("t.path", Tier.T1))
    call = _call("t.path", {"path": str(target)})
    decision = decide(call, "safe", _ctx())
    assert decision.action == "consent"
    assert "files.documents:write" in decision.scopes


def test_path_scopes_read_for_t0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # where Windows looks for home
    docs = tmp_path / "Documents"
    docs.mkdir()
    target = docs / "note.txt"
    target.write_text("x", encoding="utf-8")
    registry.register(ToolSpec("t.path", Tier.T0))
    call = _call("t.path", {"path": str(target)})
    decision = decide(call, "safe", _ctx())
    assert decision.action == "consent"
    assert "files.documents:read" in decision.scopes


def test_confirm_has_prompt() -> None:
    registry.register(ToolSpec("t.confirm", Tier.T1))
    call = _call("t.confirm")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "confirm"
    assert decision.prompt is not None
    assert len(decision.prompt) > 0


def test_run_has_no_prompt() -> None:
    registry.register(ToolSpec("t.run", Tier.T0))
    call = _call("t.run")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "run"
    assert decision.prompt is None


def test_deny_has_no_prompt() -> None:
    call = _call("no.such.tool")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "deny"
    assert decision.prompt is None


def test_run_kind_is_none() -> None:
    registry.register(ToolSpec("t.run", Tier.T0))
    call = _call("t.run")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "run"
    assert decision.kind is None


def test_deny_kind_is_none() -> None:
    call = _call("no.such.tool")
    decision = decide(call, "safe", _ctx())
    assert decision.action == "deny"
    assert decision.kind is None


def test_allow_list_exempts_the_path_from_the_consent_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # where Windows looks for home
    (tmp_path / "Documents" / "ok").mkdir(parents=True)
    registry.register(ToolSpec("t.path", Tier.T1))
    call = _call("t.path", {"path": str(tmp_path / "Documents" / "ok" / "a.txt")})
    assert decide(call, "balanced", _ctx()).action == "consent"
    allowed = PolicySettings(allow_paths=[str(tmp_path / "Documents" / "ok")])
    decision = decide(call, "balanced", _ctx(allowed))
    assert (decision.action, decision.scopes) == ("run", ())
    assert decide(call, "safe", _ctx(allowed)).action == "confirm"
