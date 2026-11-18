"""The brain reaches the system controls through the gate like the other tools (t11)."""

import asyncio

import pytest

from jarvis.brain.failures import ToolError
from jarvis.brain.system_tools import call_system
from jarvis.system import SYSTEM_TOOLS  # noqa: F401 - registers the system tools' policy
from jarvis.system.controls import SystemError


class FakeSystem:
    """Records each control call without touching the machine."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def output_device(self, device: int) -> dict[str, object]:
        self.calls.append(("output_device", device))
        return {"devices": ["45. Speakers"], "active": 45}

    def dnd(self, on: bool) -> dict[str, object]:
        self.calls.append(("dnd", on))
        return {"dnd": on}

    def media(self, action: str) -> dict[str, object]:
        self.calls.append(("media", action))
        return {"media": action}

    def power(self, action: str) -> dict[str, object]:
        self.calls.append(("power", action))
        return {"power": action}

    def open_url(self, url: str) -> dict[str, object]:
        self.calls.append(("open_url", url))
        return {"opened": url}

    def info(self) -> dict[str, object]:
        self.calls.append(("info", None))
        return {
            "battery": 73,
            "memory_used_percent": 50.0,
            "disk_used_percent": 30.0,
            "uptime_s": 10,
        }


def test_should_refuse_unknown_keys_and_actions() -> None:
    system = FakeSystem()
    with pytest.raises(ToolError, match=r"expected arguments on"):
        asyncio.run(call_system(system, "system.dnd", {"loudly": True}))  # type: ignore[arg-type]
    with pytest.raises(ToolError, match=r"action must be"):
        asyncio.run(call_system(system, "system.power", {"action": "format"}))  # type: ignore[arg-type]


def test_should_turn_a_control_error_into_a_tool_error() -> None:
    class Broken(FakeSystem):
        def dnd(self, on: bool) -> dict[str, object]:
            raise SystemError(
                "UNSUPPORTED_ON_PLATFORM",
                "gsettings is not installed — install GNOME's settings daemon",
            )

    with pytest.raises(ToolError, match=r"UNSUPPORTED_ON_PLATFORM"):
        asyncio.run(call_system(Broken(), "system.dnd", {"on": True}))  # type: ignore[arg-type]
