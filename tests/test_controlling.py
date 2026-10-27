"""FR-SAFE-06: 'Jarvis is controlling your PC' with Stop, while input tools run."""

import asyncio
import json

import pytest

from jarvis.hud.page import read_page
from jarvis.orchestrator.controlling import CONTROLLING, ControlIndicator
from jarvis.orchestrator.hud import HudEvent
from jarvis.policy import Tier
from tests.gated_rig import Impl, clean_state, dispatch, tool  # noqa: F401
from tests.orchestrator_rig import FakeBrain, make_rig
from tests.test_hud_clickthrough import _load_window


def _indicator() -> tuple[ControlIndicator, list[HudEvent]]:
    events: list[HudEvent] = []

    async def hud(event: HudEvent) -> None:
        events.append(event)

    return ControlIndicator(hud), events


def test_should_show_once_for_nested_input_tools_and_take_it_down_after() -> None:
    indicator, events = _indicator()

    async def scenario() -> None:
        async with indicator.driving(), indicator.driving():
            pass

    asyncio.run(scenario())
    assert [(e.text, e.extra) for e in events] == [
        (CONTROLLING, {"stop": True}),
        ("", {"closed": True}),
    ]


def test_should_take_it_down_when_the_tool_fails() -> None:
    indicator, events = _indicator()

    async def scenario() -> None:
        async with indicator.driving():
            raise RuntimeError("xtest gone")

    with pytest.raises(RuntimeError):
        asyncio.run(scenario())
    assert events[-1].extra == {"closed": True}


class Probe:
    def __init__(self) -> None:
        self.log: list[str] = []

    def driving(self) -> "Probe":
        return self

    async def __aenter__(self) -> None:
        self.log.append("shown")

    async def __aexit__(self, *exc: object) -> None:
        self.log.append("hidden")


@pytest.mark.parametrize(("drives", "expected"), [(True, ["shown", "hidden"]), (False, [])])
def test_should_show_it_around_an_input_tool_only(drives: bool, expected: list[str]) -> None:
    tool("t.type", Tier.T0, drives_input=drives)
    probe = Probe()
    _, _, impl = dispatch("t.type", {}, mode="yolo", controlling=probe.driving)
    assert len(impl.calls) == 1 and probe.log == expected


def test_should_show_it_on_the_hud_from_a_brain_turn(tmp_path: object) -> None:
    async def script(on_say: object, on_ask: object) -> object:
        ctx = rig.trace.ctx
        assert ctx is not None
        async with ctx.controlling():
            pass
        return FakeBrain().final

    rig = make_rig(tmp_path, FakeBrain(script=script))  # type: ignore[arg-type]
    from tests.orchestrator_rig import command  # noqa: PLC0415

    asyncio.run(rig.runner.run(command("type hello", None)))
    shown = [e for e in rig.hud_events if e.state == "controlling"]
    assert [e.text for e in shown] == [CONTROLLING, ""]


def test_should_take_clicks_but_never_focus_for_the_stop_bar() -> None:
    window = _load_window()
    bar = json.dumps({"interactive": True, "focus": False, "rect": [16, 300, 580, 50]})
    card = json.dumps({"interactive": True, "focus": True, "rect": [16, 100, 580, 220]})
    assert window.parse_mode(bar) == (16, 300, 580, 50)
    assert window.wants_focus(bar) is False
    assert window.wants_focus(card) is True
    assert window.wants_focus(json.dumps({"interactive": False, "focus": True})) is False
    assert window.wants_focus("nope") is False


def test_should_post_stop_from_the_bar_with_the_token() -> None:
    page = read_page()
    stop = page[page.index("getElementById('control-stop')") :]
    assert "fetch('/stop'" in stop[:300] and "'Bearer ' + token" in stop[:300]
    assert "focus: el === card" in page  # only the card asks for the keyboard
