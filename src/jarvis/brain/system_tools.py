"""Validate and route the brain's system-control calls (FR-PC-06/07/13): names in, controls out."""

import asyncio
from collections.abc import Callable, Mapping
from typing import Protocol

from jarvis.brain.failures import ToolError
from jarvis.system.controls import SystemError

__all__ = ["SystemLike", "call_system"]

_MAX_URL = 2048

_MEDIA_ACTIONS = ("play", "pause", "toggle", "next", "previous")
_POWER_ACTIONS = ("sleep", "signout", "restart", "shutdown")


class SystemLike(Protocol):
    """The system-controls surface the brain uses (jarvis.system.controls.SystemControls)."""

    def output_device(self, device: int) -> dict[str, object]: ...

    def dnd(self, on: bool) -> dict[str, object]: ...

    def dark_mode(self, on: bool) -> dict[str, object]: ...

    def night_light(self, on: bool) -> dict[str, object]: ...

    def brightness(self, level: int) -> dict[str, object]: ...

    def media(self, action: str) -> dict[str, object]: ...

    def wifi(self, on: bool) -> dict[str, object]: ...

    def bluetooth(self, on: bool) -> dict[str, object]: ...

    def lock(self) -> dict[str, object]: ...

    def power(self, action: str) -> dict[str, object]: ...

    def open_url(self, url: str) -> dict[str, object]: ...

    def info(self) -> dict[str, object]: ...


def _keys(name: str, args: Mapping[str, object], required: frozenset[str]) -> None:
    keys = set(args)
    if keys != required:
        wanted = ", ".join(sorted(required)) or "none"
        raise ToolError(f"{name}: expected arguments {wanted}")


def _flag(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise ToolError(f"{what} must be true or false")
    return value


def _level(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ToolError("level must be an integer from 1 to 100")
    return value


def _device(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ToolError("device must be an index from the list (0 lists the output devices)")
    return value


def _url(value: object) -> str:
    if not isinstance(value, str):
        raise ToolError("url must be a string")
    stripped = value.strip()
    if not stripped.startswith(("http://", "https://")) or len(stripped) > _MAX_URL:
        raise ToolError(
            f"url must start with http:// or https:// and be at most {_MAX_URL} characters"
        )
    return stripped


def _media(value: object) -> str:
    if value not in _MEDIA_ACTIONS:
        raise ToolError("action must be play, pause, toggle, next or previous")
    return str(value)


def _power(value: object) -> str:
    if value not in _POWER_ACTIONS:
        raise ToolError("action must be sleep, signout, restart or shutdown")
    return str(value)


async def call_system(
    system: SystemLike, policy_name: str, args: Mapping[str, object]
) -> dict[str, object]:
    """Validate and run one `system.*` call; control errors become ToolError with their code."""
    try:
        return await asyncio.to_thread(_call, system, policy_name, args)
    except SystemError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from None
    except (OSError, ValueError) as exc:
        raise ToolError(f"INTERNAL: {exc}") from None


_Run = Callable[[SystemLike, Mapping[str, object]], dict[str, object]]

_ROUTES: dict[str, tuple[frozenset[str], _Run]] = {
    "system.output_device": (
        frozenset({"device"}),
        lambda s, a: s.output_device(_device(a["device"])),
    ),
    "system.dnd": (frozenset({"on"}), lambda s, a: s.dnd(_flag(a["on"], "on"))),
    "system.dark_mode": (frozenset({"on"}), lambda s, a: s.dark_mode(_flag(a["on"], "on"))),
    "system.night_light": (frozenset({"on"}), lambda s, a: s.night_light(_flag(a["on"], "on"))),
    "system.brightness": (frozenset({"level"}), lambda s, a: s.brightness(_level(a["level"]))),
    "system.media": (frozenset({"action"}), lambda s, a: s.media(_media(a["action"]))),
    "system.wifi": (frozenset({"on"}), lambda s, a: s.wifi(_flag(a["on"], "on"))),
    "system.bluetooth": (frozenset({"on"}), lambda s, a: s.bluetooth(_flag(a["on"], "on"))),
    "system.lock": (frozenset(), lambda s, _a: s.lock()),
    "system.power": (frozenset({"action"}), lambda s, a: s.power(_power(a["action"]))),
    "system.open_url": (frozenset({"url"}), lambda s, a: s.open_url(_url(a["url"]))),
    "system.info": (frozenset(), lambda s, _a: s.info()),
}


def _call(system: SystemLike, policy_name: str, args: Mapping[str, object]) -> dict[str, object]:
    """Validate one `system.*` call and run it on the controls (call_system puts it on a thread)."""
    route = _ROUTES.get(policy_name)
    if route is None:
        raise ToolError(f"unknown system tool {policy_name}")
    required, run = route
    _keys(policy_name, args, required)
    return run(system, args)
