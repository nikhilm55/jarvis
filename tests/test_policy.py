"""Tests for the policy registry, ToolSpec validation and the M1 behaviours `decide` keeps."""

import pytest

from jarvis.policy import Mode, Tier, ToolSpec, get, register, registry
from jarvis.policy.decide import decide
from jarvis.policy.decision import ToolCall, TurnContext

MODES: tuple[Mode, ...] = ("safe", "balanced", "yolo")


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


def verdict(name: object, mode: Mode, args: dict[str, object] | None = None) -> tuple[str, str]:
    call = ToolCall(name, args or {}, "internal")  # type: ignore[arg-type]
    decision = decide(call, mode, TurnContext("t1"))
    return decision.action, decision.reason


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
        "desktop.list_apps": Tier.T0,
        "desktop.is_running": Tier.T0,
        "desktop.list_windows": Tier.T0,
        "desktop.focus_window": Tier.T1,
        "desktop.window_op": Tier.T1,
        "desktop.volume_get": Tier.T0,
        "desktop.volume_set": Tier.T1,  # R95: FRS 5.10 lists volume under T1
        "desktop.volume_step": Tier.T1,
        "desktop.mute": Tier.T1,
    }
    for name, tier in expected.items():
        spec = get(name)
        assert spec is not None
        assert spec.tier == tier
        assert spec.scopes == ()


def test_should_deny_when_tool_unknown() -> None:
    assert verdict("nope", "safe") == ("deny", "unknown tool")


@pytest.mark.parametrize("name", [42, ["desktop.volume_get"], None])
def test_should_deny_when_tool_name_is_not_a_hashable_str(name: object) -> None:
    assert verdict(name, "safe") == ("deny", "unknown tool")


def test_should_deny_when_mode_unknown_even_for_t0() -> None:
    assert verdict("desktop.volume_get", "warp") == ("deny", "unknown mode")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name", ["Desktop.Volume_Get", " desktop.volume_get", "desktop.volume_get\n"]
)
def test_should_deny_when_tool_name_differs_only_by_case_or_whitespace(name: str) -> None:
    assert verdict(name, "yolo")[0] == "deny"


@pytest.mark.parametrize("mode", MODES)
def test_should_run_t0_in_every_mode(mode: Mode) -> None:
    register(ToolSpec(name="tool.T0", tier=Tier.T0))
    assert verdict("tool.T0", mode) == ("run", "allowed: T0")


@pytest.mark.parametrize("mode", ["balanced", "yolo"])
def test_should_run_t1_when_balanced_or_yolo(mode: Mode) -> None:
    register(ToolSpec(name="tool.T1", tier=Tier.T1))
    assert verdict("tool.T1", mode) == ("run", "allowed: T1")


def test_should_confirm_t1_when_safe_mode() -> None:
    register(ToolSpec(name="tool.T1", tier=Tier.T1))
    assert verdict("tool.T1", "safe")[0] == "confirm"


@pytest.mark.parametrize("mode", MODES)
def test_should_ask_for_consent_unless_yolo_when_a_tool_has_scopes(mode: Mode) -> None:
    register(ToolSpec(name="scoped.tool", tier=Tier.T0, scopes=("file",)))
    assert verdict("scoped.tool", mode)[0] == ("run" if mode == "yolo" else "consent")


@pytest.mark.parametrize("name", ["desktop.open_app", "desktop.close_app"])
def test_should_confirm_open_and_close_app_when_safe_and_run_them_when_balanced(name: str) -> None:
    assert verdict(name, "safe")[0] == "confirm"
    assert verdict(name, "balanced")[0] == "run"


def test_should_run_reading_the_volume_in_every_mode() -> None:
    assert [verdict("desktop.volume_get", mode)[0] for mode in MODES] == ["run", "run", "run"]


@pytest.mark.parametrize("name", ["desktop.volume_set", "desktop.volume_step", "desktop.mute"])
def test_should_treat_changing_the_volume_as_t1_confirm_in_safe_run_otherwise(name: str) -> None:
    assert [verdict(name, mode)[0] for mode in MODES] == ["confirm", "run", "run"]


def test_should_not_mutate_args_when_deciding() -> None:
    args: dict[str, object] = {"x": 1}
    verdict("desktop.volume_get", "safe", args)
    assert args == {"x": 1}


def test_should_coerce_tier_string_when_valid() -> None:
    spec = ToolSpec("x.t", "T1")  # type: ignore[arg-type]
    assert spec.tier is Tier.T1
    register(spec)
    assert verdict("x.t", "safe")[0] == "confirm"
    assert verdict("x.t", "balanced")[0] == "run"


def test_should_coerce_scopes_list_to_tuple() -> None:
    spec = ToolSpec(name="s.tool", tier=Tier.T0, scopes=["a", "b"])  # type: ignore[arg-type]
    assert spec.scopes == ("a", "b")
    assert isinstance(spec.scopes, tuple)
    register(spec)
    assert verdict("s.tool", "safe")[0] == "consent"


@pytest.mark.parametrize("bad_tier", ["T9", "t0", "", 0, None, 1.5])
def test_should_reject_invalid_tier(bad_tier: object) -> None:
    with pytest.raises(ValueError, match="tier"):
        ToolSpec("x.t", bad_tier)  # type: ignore[arg-type]


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


def test_should_declare_closing_a_window_undoable_and_reading_windows_not() -> None:
    window_op, list_windows = get("desktop.window_op"), get("desktop.list_windows")
    assert window_op is not None
    assert list_windows is not None
    assert window_op.undoable is True  # closing is undone by reopening the app (R90)
    assert list_windows.undoable is False


@pytest.mark.parametrize(
    "name", ["desktop.list_windows", "desktop.list_apps", "desktop.is_running"]
)
def test_should_run_reading_windows_and_apps_in_every_mode(name: str) -> None:
    assert [verdict(name, mode)[0] for mode in MODES] == ["run", "run", "run"]


@pytest.mark.parametrize("name", ["desktop.focus_window", "desktop.window_op"])
def test_should_treat_changing_windows_as_t1_confirm_in_safe_run_otherwise(name: str) -> None:
    assert [verdict(name, mode)[0] for mode in MODES] == ["confirm", "run", "run"]
