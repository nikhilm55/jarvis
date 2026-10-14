"""Tests for jarvis.brain.desktop_tools.call_desktop."""

import asyncio
from typing import Any

import pytest

import jarvis.brain.desktop_tools as module
from jarvis.brain.desktop_tools import call_desktop
from jarvis.brain.failures import ToolError
from jarvis.desktop.client import DesktopError


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
