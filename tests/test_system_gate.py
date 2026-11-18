"""The system-control gate: tier per tool, mode table tiers, provenance (FR-PC-06/07/13, R83)."""

from jarvis.policy import Decision, Tier, ToolCall, TurnContext
from jarvis.policy.decide import decide
from jarvis.policy.registry import get


def decision_for(name: str, args: dict[str, object], mode: str) -> Decision:
    return decide(ToolCall(name, args, "brain"), mode, TurnContext("t", mode=mode))  # type: ignore[arg-type]


def test_should_run_a_t1_control_silently_when_balanced() -> None:
    assert decision_for("system.dnd", {"on": True}, "balanced").action == "run"


def test_should_confirm_a_t1_control_when_safe() -> None:
    assert decision_for("system.dnd", {"on": True}, "safe").action == "confirm"


def test_should_guardrail_a_t3_power_action_when_yolo() -> None:
    assert decision_for("system.power", {"action": "shutdown"}, "yolo").kind == "guardrail"


def test_should_ask_a_tier_click_for_a_t3_power_action_when_balanced() -> None:
    assert decision_for("system.power", {"action": "restart"}, "balanced").kind == "click"


def test_should_run_system_info_where_it_is_read_only() -> None:
    assert decision_for("system.info", {}, "yolo").action == "run"


def test_should_open_url_be_t1_with_r83_provenance_on_the_url() -> None:
    spec = get("system.open_url")
    assert spec is not None and spec.tier == Tier.T1 and spec.provenance_keys == ("url",)


def test_should_every_system_tool_be_registered() -> None:
    names = [
        "system.output_device",
        "system.dnd",
        "system.dark_mode",
        "system.night_light",
        "system.brightness",
        "system.media",
        "system.wifi",
        "system.bluetooth",
        "system.lock",
        "system.power",
        "system.open_url",
        "system.info",
    ]
    assert all(get(name) is not None for name in names)
