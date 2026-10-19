"""Validate and route the brain's desktop tool calls (R54): policy names in, client calls out."""

import asyncio
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any, Protocol

from jarvis.brain.failures import ToolError
from jarvis.desktop.client import DesktopError

__all__ = ["DesktopLike", "call_desktop"]

_DEFAULT_TIMEOUT_S = 12.0
_OPEN_TIMEOUT_S = 15.0
_MAX_NAME = 100
_MAX_REF = 200
_MAX_TILE = 8
WINDOW_OPS = (
    "minimize",
    "maximize",
    "restore",
    "close",
    "snap_left",
    "snap_right",
    "move_to_monitor",
    "tile",
)

_Call = Coroutine[Any, Any, dict[str, object]]


class DesktopLike(Protocol):
    """Protocol describing the async desktop client surface used by the brain."""

    async def open_app(self, query: str) -> dict[str, object]: ...

    async def close_app(self, query: str) -> dict[str, object]: ...

    async def list_windows(self) -> dict[str, object]: ...

    async def focus_window(self, ref: str) -> dict[str, object]: ...

    async def window_op(
        self, ref: str, op: str, monitor: int | None = None, with_refs: Sequence[str] = ()
    ) -> dict[str, object]: ...

    async def list_apps(self) -> dict[str, object]: ...

    async def is_running(self, query: str) -> dict[str, object]: ...

    async def volume_get(self) -> dict[str, object]: ...

    async def volume_set(self, pct: int) -> dict[str, object]: ...

    async def volume_step(self, delta: int) -> dict[str, object]: ...

    async def mute(self, on: bool) -> dict[str, object]: ...


def _check_keys(policy_name: str, args: Mapping[str, object], expected: set[str]) -> None:
    """Raise ToolError when the argument key set does not match the expected set."""
    if set(args) != expected:
        raise ToolError(f"{policy_name}: expected arguments {sorted(expected)}, got {sorted(args)}")


def _name(value: object) -> str:
    """Validate a desktop app name argument and return the stripped value."""
    if not isinstance(value, str):
        raise ToolError("name must be a string")
    stripped = value.strip()
    if not stripped:
        raise ToolError("name must be non-empty")
    if len(stripped) > _MAX_NAME:
        raise ToolError(f"name must be at most {_MAX_NAME} characters")
    if not all(ch.isprintable() for ch in stripped):
        raise ToolError("name must not contain control characters")
    return stripped


def _text(label: str, value: object, limit: int) -> str:
    """Validate a short printable string argument and return it stripped."""
    if not isinstance(value, str):
        raise ToolError(f"{label} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ToolError(f"{label} must be non-empty")
    if len(stripped) > limit:
        raise ToolError(f"{label} must be at most {limit} characters")
    if not all(ch.isprintable() for ch in stripped):
        raise ToolError(f"{label} must not contain control characters")
    return stripped


def _int(label: str, value: object, low: int, high: int) -> int:
    """Validate an integer argument within a range and return it."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{label} must be an integer from {low} to {high}")
    if not low <= value <= high:
        raise ToolError(f"{label} must be an integer from {low} to {high}")
    return value


def _open_app(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the open_app coroutine."""
    _check_keys("desktop.open_app", args, {"name"})
    return desktop.open_app(_name(args["name"]))  # gate-ok: via MCP impl


def _close_app(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the close_app coroutine."""
    _check_keys("desktop.close_app", args, {"name"})
    return desktop.close_app(_name(args["name"]))  # gate-ok: via MCP impl


def _list_windows(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the list_windows coroutine."""
    _check_keys("desktop.list_windows", args, set())
    return desktop.list_windows()  # gate-ok: via MCP impl


def _focus_window(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the focus_window coroutine."""
    _check_keys("desktop.focus_window", args, {"ref"})
    return desktop.focus_window(_text("ref", args["ref"], _MAX_REF))  # gate-ok: via MCP impl


def _window_op(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the window_op coroutine."""
    unknown = set(args) - {"ref", "op", "monitor", "with_refs"}
    if unknown or not {"ref", "op"} <= set(args):
        raise ToolError("desktop.window_op: expected ref, op and optionally monitor, with_refs")
    op = _text("op", args["op"], 20)
    if op not in WINDOW_OPS:
        raise ToolError(f"op must be one of {', '.join(WINDOW_OPS)}")
    monitor = args.get("monitor")
    others = args.get("with_refs", [])
    if not isinstance(others, list) or len(others) > _MAX_TILE:
        raise ToolError(f"with_refs must be a list of at most {_MAX_TILE} window refs")
    return desktop.window_op(  # gate-ok: via MCP impl
        _text("ref", args["ref"], _MAX_REF),
        op,
        None if monitor is None else _int("monitor", monitor, 0, 15),
        [_text("with_refs item", item, _MAX_REF) for item in others],
    )


def _list_apps(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the list_apps coroutine."""
    _check_keys("desktop.list_apps", args, set())
    return desktop.list_apps()  # gate-ok: via MCP impl


def _is_running(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the is_running coroutine."""
    _check_keys("desktop.is_running", args, {"name"})
    return desktop.is_running(_name(args["name"]))  # gate-ok: via MCP impl


def _volume_get(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the volume_get coroutine."""
    _check_keys("desktop.volume_get", args, set())
    return desktop.volume_get()  # gate-ok: via MCP impl


def _volume_set(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the volume_set coroutine."""
    _check_keys("desktop.volume_set", args, {"percent"})
    return desktop.volume_set(_int("percent", args["percent"], 0, 100))  # gate-ok: via MCP impl


def _volume_step(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the volume_step coroutine."""
    _check_keys("desktop.volume_step", args, {"delta"})
    return desktop.volume_step(_int("delta", args["delta"], -100, 100))  # gate-ok: via MCP impl


def _mute(desktop: DesktopLike, args: Mapping[str, object]) -> _Call:
    """Validate and build the mute coroutine."""
    _check_keys("desktop.mute", args, {"on"})
    if not isinstance(args["on"], bool):
        raise ToolError("on must be a boolean")
    return desktop.mute(args["on"])  # gate-ok: via MCP impl


_HANDLERS: dict[str, Callable[[DesktopLike, Mapping[str, object]], _Call]] = {
    "desktop.open_app": _open_app,
    "desktop.close_app": _close_app,
    "desktop.list_windows": _list_windows,
    "desktop.focus_window": _focus_window,
    "desktop.window_op": _window_op,
    "desktop.list_apps": _list_apps,
    "desktop.is_running": _is_running,
    "desktop.volume_get": _volume_get,
    "desktop.volume_set": _volume_set,
    "desktop.volume_step": _volume_step,
    "desktop.mute": _mute,
}


def _prepare(desktop: DesktopLike, policy_name: str, args: Mapping[str, object]) -> _Call:
    """Validate arguments and return the coroutine for the requested desktop tool."""
    handler = _HANDLERS.get(policy_name)
    if handler is None:
        raise ToolError(f"unknown desktop tool {policy_name}")
    return handler(desktop, args)


async def call_desktop(
    desktop: DesktopLike,
    policy_name: str,
    args: Mapping[str, object],
    *,
    timeout_s: float | None = None,
) -> dict[str, object]:
    """Validate and run a desktop tool call; timeouts and client errors become ToolError."""
    coro = _prepare(desktop, policy_name, args)
    effective = (
        timeout_s
        if timeout_s is not None
        else (_OPEN_TIMEOUT_S if policy_name == "desktop.open_app" else _DEFAULT_TIMEOUT_S)
    )
    try:
        async with asyncio.timeout(effective):
            return await coro
    except TimeoutError:
        raise ToolError(f"{policy_name} timed out; check whether it took effect") from None
    except DesktopError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from None
