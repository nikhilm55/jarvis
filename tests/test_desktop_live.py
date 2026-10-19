"""Live desktop test driving the real GNOME X11 desktop. It opens Calculator, works on that one
window only, and closes it again; it never touches another window."""

import asyncio
import contextlib
import os

import pytest

from jarvis.desktop.client import DesktopClient, DesktopError
from jarvis.desktop.windows import parse_ref
from jarvis.desktop.x11 import list_windows
from jarvis.desktop.xport import open_port
from jarvis.policy import ToolCall, TurnContext, decide

pytestmark = [
    pytest.mark.desktop,
    pytest.mark.skipif(
        not os.environ.get("DISPLAY") or os.environ.get("JARVIS_LIVE_DESKTOP") != "1",
        reason="live desktop test: set DISPLAY and JARVIS_LIVE_DESKTOP=1",
    ),
]

TOOLS = (
    "desktop.open_app",
    "desktop.close_app",
    "desktop.list_windows",
    "desktop.focus_window",
    "desktop.window_op",
)


def test_should_open_calculator_focused_and_in_front_then_manage_and_close_it_when_live() -> None:
    asyncio.run(scenario())


def _calculator_windows() -> list[int]:
    return [w.window_id for w in list_windows() if "calculator" in w.wm_class.casefold()]


async def _state(client: DesktopClient, ref: str) -> list[str]:
    listing = await client.list_windows()
    windows = listing["windows"]
    assert isinstance(windows, list)
    (mine,) = [w for w in windows if isinstance(w, dict) and w["ref"] == ref]
    state = mine["state"]
    assert isinstance(state, list)
    return [str(s) for s in state]


async def scenario() -> None:
    for tool in TOOLS:
        call = ToolCall(tool, {"query": "calculator"}, "internal")
        assert decide(call, "balanced", TurnContext("live")).action == "run"

    if _calculator_windows():
        pytest.skip("Calculator is already open - not touching the user's windows")

    client = DesktopClient()
    try:
        opened = await client.open_app("calculator")  # S1: focused and in front
        assert opened["focused"] is True
        ref = str(opened["ref"])
        wid = parse_ref(ref)
        assert wid is not None
        with open_port() as port:
            assert port.active_window() == wid  # _NET_ACTIVE_WINDOW is Calculator
            assert port.stacking()[-1] == wid
        assert "focused" in await _state(client, ref)

        await client.window_op(ref, "minimize")
        assert "minimized" in await _state(client, ref)
        await client.focus_window(ref)  # restores it first
        state = await _state(client, ref)
        assert "minimized" not in state
        assert "focused" in state

        await client.window_op(ref, "maximize")
        assert "maximized" in await _state(client, ref)
        await client.window_op(ref, "restore")
        assert "maximized" not in await _state(client, ref)

        await client.window_op(ref, "snap_left")
        with open_port() as port:
            area, rect = port.workarea(), port.rect(wid)
            assert rect is not None
            left, right, top, bottom = port.frame_extents(wid)
            frame = (rect.x - left, rect.y - top, rect.w + left + right, rect.h + top + bottom)
            assert all(
                abs(got - want) <= 10
                for got, want in zip(frame, (area.x, area.y, area.w // 2, area.h), strict=True)
            )  # the left half of the working area, within 10 px

        with pytest.raises(DesktopError) as bad:
            await client.window_op(ref, "move_to_monitor", 9)
        assert bad.value.code == "INVALID_ARGUMENT"

        await client.window_op(ref, "close")
        for _ in range(50):
            await asyncio.sleep(0.1)
            if wid not in _calculator_windows():
                break
        else:
            pytest.fail("Calculator window still open")
    finally:
        with contextlib.suppress(Exception):
            await client.close_app("calculator")  # leave nothing open, whatever happened
        await client.close()
