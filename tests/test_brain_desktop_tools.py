"""Tests for jarvis.brain.desktop_tools.call_desktop."""

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

import jarvis.brain.desktop_tools as module
from jarvis.brain.desktop_tools import call_desktop
from jarvis.brain.failures import ToolError
from jarvis.desktop.client import DesktopError
from jarvis.desktop.windows import WINDOW_OPS as MANAGER_OPS


class FakeDesktop:
    """A fake desktop client that records calls and can simulate errors/delays."""

    def __init__(self, error: Exception | None = None, delay_s: float = 0.0) -> None:
        self.calls: list[tuple[object, ...]] = []
        self._error = error
        self._delay_s = delay_s

    async def _maybe_delay(self) -> None:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)

    async def open_app(self, query: str) -> dict[str, object]:
        self.calls.append(("open_app", query))
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def close_app(self, query: str) -> dict[str, object]:
        self.calls.append(("close_app", query))
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def _answer(self, *call: object) -> dict[str, object]:
        self.calls.append(call)
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def list_windows(self) -> dict[str, object]:
        return await self._answer("list_windows")

    async def focus_window(self, ref: str) -> dict[str, object]:
        return await self._answer("focus_window", ref)

    async def window_op(
        self, ref: str, op: str, monitor: int | None = None, with_refs: Sequence[str] = ()
    ) -> dict[str, object]:
        return await self._answer("window_op", ref, op, monitor, list(with_refs))

    async def list_apps(self) -> dict[str, object]:
        return await self._answer("list_apps")

    async def is_running(self, query: str) -> dict[str, object]:
        return await self._answer("is_running", query)

    async def volume_get(self) -> dict[str, object]:
        self.calls.append(("volume_get",))
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def volume_set(self, pct: int) -> dict[str, object]:
        self.calls.append(("volume_set", pct))
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def volume_step(self, delta: int) -> dict[str, object]:
        self.calls.append(("volume_step", delta))
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def mute(self, on: bool) -> dict[str, object]:
        self.calls.append(("mute", on))
        await self._maybe_delay()
        if self._error is not None:
            raise self._error
        return {"ok": True}

    async def type_text(self, text: str) -> dict[str, object]:
        return await self._answer("type_text", text)

    async def press_keys(self, combo: str) -> dict[str, object]:
        return await self._answer("press_keys", combo)

    async def click(
        self, x: int, y: int, button: str = "left", count: int = 1
    ) -> dict[str, object]:
        return await self._answer("click", x, y, button, count)

    async def scroll(self, dx: int, dy: int) -> dict[str, object]:
        return await self._answer("scroll", dx, dy)


def test_should_strip_whitespace_when_open_app_called() -> None:
    """open_app maps MCP arg 'name' to client 'query' with whitespace stripped."""
    fake = FakeDesktop()
    result = asyncio.run(call_desktop(fake, "desktop.open_app", {"name": "  Calculator "}))
    assert fake.calls == [("open_app", "Calculator")]
    assert result == {"ok": True}


def test_should_strip_whitespace_when_close_app_called() -> None:
    """close_app maps MCP arg 'name' to client 'query' with whitespace stripped."""
    fake = FakeDesktop()
    result = asyncio.run(call_desktop(fake, "desktop.close_app", {"name": "  Calculator "}))
    assert fake.calls == [("close_app", "Calculator")]
    assert result == {"ok": True}


def test_should_return_client_dict_unchanged_when_open_app_succeeds() -> None:
    """The dict returned by the client is returned unchanged."""
    fake = FakeDesktop()
    result = asyncio.run(call_desktop(fake, "desktop.open_app", {"name": "Calc"}))
    assert result == {"ok": True}


def test_should_call_volume_get_when_args_empty() -> None:
    """volume_get with {} calls volume_get."""
    fake = FakeDesktop()
    asyncio.run(call_desktop(fake, "desktop.volume_get", {}))
    assert fake.calls == [("volume_get",)]


def test_should_call_volume_set_when_percent_given() -> None:
    """volume_set with {"percent": 30} calls volume_set(30)."""
    fake = FakeDesktop()
    asyncio.run(call_desktop(fake, "desktop.volume_set", {"percent": 30}))
    assert fake.calls == [("volume_set", 30)]


def test_should_call_volume_step_when_delta_given() -> None:
    """volume_step with {"delta": -10} calls volume_step(-10)."""
    fake = FakeDesktop()
    asyncio.run(call_desktop(fake, "desktop.volume_step", {"delta": -10}))
    assert fake.calls == [("volume_step", -10)]


def test_should_call_mute_when_on_given() -> None:
    """mute with {"on": True} calls mute(True)."""
    fake = FakeDesktop()
    asyncio.run(call_desktop(fake, "desktop.mute", {"on": True}))
    assert fake.calls == [("mute", True)]


@pytest.mark.parametrize(
    "policy_name, args",
    [
        ("desktop.open_app", {}),
        ("desktop.open_app", {"name": ""}),
        ("desktop.open_app", {"name": "   "}),
        ("desktop.open_app", {"name": 5}),
        ("desktop.open_app", {"name": "x" * 101}),
        ("desktop.open_app", {"name": "bad\x00name"}),
        ("desktop.open_app", {"name": "a", "extra": 1}),
        ("desktop.volume_set", {"percent": 101}),
        ("desktop.volume_set", {"percent": -1}),
        ("desktop.volume_set", {"percent": "30"}),
        ("desktop.volume_set", {"percent": 30.5}),
        ("desktop.volume_set", {"percent": True}),
        ("desktop.volume_step", {"delta": 101}),
        ("desktop.volume_step", {"delta": True}),
        ("desktop.mute", {"on": "yes"}),
        ("desktop.mute", {"on": 1}),
        ("desktop.volume_get", {"x": 1}),
    ],
)
def test_should_raise_tool_error_when_bad_input(policy_name: str, args: dict[str, Any]) -> None:
    """Bad input raises ToolError and the fake is NOT called."""
    fake = FakeDesktop()
    with pytest.raises(ToolError):
        asyncio.run(call_desktop(fake, policy_name, args))
    assert fake.calls == []


def test_should_raise_tool_error_when_unknown_policy_name() -> None:
    """An unknown policy name raises ToolError mentioning 'unknown'."""
    fake = FakeDesktop()
    with pytest.raises(ToolError, match="unknown"):
        asyncio.run(call_desktop(fake, "desktop.rm_rf", {}))


def test_should_wrap_desktop_error_when_client_raises_not_found() -> None:
    """A DesktopError from the client becomes a ToolError with code and message."""
    fake = FakeDesktop(error=DesktopError("NOT_FOUND", "no such app"))
    with pytest.raises(ToolError, match="NOT_FOUND") as exc_info:
        asyncio.run(call_desktop(fake, "desktop.open_app", {"name": "Calc"}))
    assert "no such app" in str(exc_info.value)


def test_should_raise_tool_error_when_client_times_out() -> None:
    """A slow client with timeout_s=0.05 raises ToolError mentioning 'timed out'."""
    fake = FakeDesktop(delay_s=1.0)
    with pytest.raises(ToolError, match="timed out"):
        asyncio.run(call_desktop(fake, "desktop.open_app", {"name": "Calc"}, timeout_s=0.05))


def test_should_have_longer_open_timeout_when_compared_to_default() -> None:
    """The default timeout for open_app is longer than for other tools."""
    assert module._OPEN_TIMEOUT_S > module._DEFAULT_TIMEOUT_S


@pytest.mark.parametrize(
    ("tool", "args", "call"),
    [
        ("desktop.list_windows", {}, ("list_windows",)),
        ("desktop.list_apps", {}, ("list_apps",)),
        ("desktop.is_running", {"name": " Firefox "}, ("is_running", "Firefox")),
        ("desktop.focus_window", {"ref": " x11:0x1a "}, ("focus_window", "x11:0x1a")),
        (
            "desktop.window_op",
            {"ref": "firefox", "op": "snap_left"},
            ("window_op", "firefox", "snap_left", None, []),
        ),
        (
            "desktop.window_op",
            {"ref": "a", "op": "move_to_monitor", "monitor": 1},
            ("window_op", "a", "move_to_monitor", 1, []),
        ),
        (
            "desktop.window_op",
            {"ref": "a", "op": "tile", "with_refs": [" b ", "c"]},
            ("window_op", "a", "tile", None, ["b", "c"]),
        ),
    ],
)
def test_should_forward_the_window_and_app_tools_with_checked_arguments(
    tool: str, args: dict[str, object], call: tuple[object, ...]
) -> None:
    fake = FakeDesktop()
    asyncio.run(call_desktop(fake, tool, args))
    assert fake.calls == [call]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("desktop.list_windows", {"x": 1}),
        ("desktop.list_apps", {"x": 1}),
        ("desktop.is_running", {}),
        ("desktop.is_running", {"name": " "}),
        ("desktop.focus_window", {}),
        ("desktop.focus_window", {"ref": ""}),
        ("desktop.focus_window", {"ref": 5}),
        ("desktop.focus_window", {"ref": "x" * 201}),
        ("desktop.focus_window", {"ref": "a\x00b"}),
        ("desktop.focus_window", {"ref": "a", "extra": 1}),
        ("desktop.window_op", {"ref": "a"}),
        ("desktop.window_op", {"op": "close"}),
        ("desktop.window_op", {"ref": "a", "op": "explode"}),
        ("desktop.window_op", {"ref": "a", "op": 3}),
        ("desktop.window_op", {"ref": "a", "op": "close", "extra": 1}),
        ("desktop.window_op", {"ref": "a", "op": "move_to_monitor", "monitor": -1}),
        ("desktop.window_op", {"ref": "a", "op": "move_to_monitor", "monitor": 16}),
        ("desktop.window_op", {"ref": "a", "op": "move_to_monitor", "monitor": True}),
        ("desktop.window_op", {"ref": "a", "op": "tile", "with_refs": "b"}),
        ("desktop.window_op", {"ref": "a", "op": "tile", "with_refs": [1]}),
        ("desktop.window_op", {"ref": "a", "op": "tile", "with_refs": ["b"] * 9}),
    ],
)
def test_should_refuse_bad_arguments_to_the_window_and_app_tools(
    tool: str, args: dict[str, object]
) -> None:
    fake = FakeDesktop()
    with pytest.raises(ToolError):
        asyncio.run(call_desktop(fake, tool, args))
    assert fake.calls == []


def test_should_offer_the_brain_exactly_the_ops_the_window_manager_has() -> None:
    assert module.WINDOW_OPS == MANAGER_OPS
