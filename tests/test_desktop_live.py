"""Live desktop test driving the real GNOME X11 desktop."""

import asyncio
import contextlib
import os

import pytest

from jarvis.desktop.client import DesktopClient
from jarvis.desktop.x11 import list_windows
from jarvis.policy import gate

pytestmark = [
    pytest.mark.desktop,
    pytest.mark.skipif(
        not os.environ.get("DISPLAY") or os.environ.get("JARVIS_LIVE_DESKTOP") != "1",
        reason="live desktop test: set DISPLAY and JARVIS_LIVE_DESKTOP=1",
    ),
]


def test_should_open_and_close_calculator_when_driven_live() -> None:
    asyncio.run(scenario())


async def scenario() -> None:
    assert gate("desktop.open_app", {"query": "calculator"}, "balanced").allowed
    assert gate("desktop.close_app", {"query": "calculator"}, "balanced").allowed

    if any("calculator" in w.wm_class.casefold() for w in list_windows()):
        pytest.skip("Calculator is already open - not touching the user's windows")

    client = DesktopClient()
    opened_flag = False
    try:
        opened_flag = True  # from here on, make sure the window we caused gets closed
        opened = await client.open_app("calculator")
        assert isinstance(opened, dict)
        app = opened.get("app")
        assert isinstance(app, str) and "Calculator" in app
        ids = opened.get("window_ids_new")
        assert isinstance(ids, list) and len(ids) > 0
        current = [w.window_id for w in list_windows()]
        assert all(i in current for i in ids)

        closed = await client.close_app("calculator")
        assert isinstance(closed, dict)
        n = closed.get("closed")
        assert isinstance(n, int) and n >= 1

        for _ in range(50):
            await asyncio.sleep(0.1)
            if not any(i in [w.window_id for w in list_windows()] for i in ids):
                break
        else:
            pytest.fail("Calculator window still open")
    finally:
        if opened_flag:
            with contextlib.suppress(Exception):
                await client.close_app("calculator")
        await client.close()
