"""Validate and route the brain's shell tool calls: `shell.run` to a runner behind the gate."""

import asyncio
from collections.abc import Coroutine, Mapping
from typing import Any, Protocol

from jarvis.brain.failures import ToolError
from jarvis.policy.shell import MAX_COMMAND_LENGTH

__all__ = ["ShellLike", "call_shell"]

_MIN_TIMEOUT_S = 1
_MAX_TIMEOUT_S = 300
_MAX_CWD = 1000

_Call = Coroutine[Any, Any, dict[str, object]]


class ShellLike(Protocol):
    """Protocol describing the shell runner surface: a blocking run, done on a worker thread."""

    def run(
        self, cmd: str, cwd: str | None = None, timeout_s: float | None = None
    ) -> dict[str, object]: ...


def _cmd(value: object) -> str:
    """Validate the command line argument."""
    if not isinstance(value, str):
        raise ToolError("cmd must be a string")
    stripped = value.strip()
    if not stripped:
        raise ToolError("cmd must be non-empty")
    if len(stripped) > MAX_COMMAND_LENGTH:
        raise ToolError(f"cmd must be at most {MAX_COMMAND_LENGTH} characters")
    return stripped


def _cwd(value: object) -> str:
    """Validate the optional working-directory argument."""
    if not isinstance(value, str):
        raise ToolError("cwd must be a string")
    stripped = value.strip()
    if not stripped:
        raise ToolError("cwd must be non-empty when given")
    if len(stripped) > _MAX_CWD:
        raise ToolError(f"cwd must be at most {_MAX_CWD} characters")
    if not all(ch.isprintable() for ch in stripped):
        raise ToolError("cwd must not contain control characters")
    return stripped


def _timeout(value: object) -> int:
    """Validate the optional timeout argument."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"timeout_s must be an integer from {_MIN_TIMEOUT_S} to {_MAX_TIMEOUT_S}")
    if not _MIN_TIMEOUT_S <= value <= _MAX_TIMEOUT_S:
        raise ToolError(f"timeout_s must be an integer from {_MIN_TIMEOUT_S} to {_MAX_TIMEOUT_S}")
    return value


async def call_shell(
    runner: ShellLike, policy_name: str, args: Mapping[str, object]
) -> dict[str, object]:
    """Validate one `shell.*` call and run it on the runner in a worker thread."""
    if policy_name != "shell.run":
        raise ToolError(f"unknown shell tool {policy_name}")
    unknown = set(args) - {"cmd", "cwd", "timeout_s"}
    if unknown or "cmd" not in args:
        raise ToolError("shell.run: expected cmd and optionally cwd, timeout_s")
    cmd = _cmd(args["cmd"])
    cwd = _cwd(args["cwd"]) if args.get("cwd") is not None else None
    timeout_s = _timeout(args["timeout_s"]) if args.get("timeout_s") is not None else None
    try:
        return await asyncio.to_thread(runner.run, cmd, cwd, timeout_s)
    except FileNotFoundError as exc:
        raise ToolError(
            f"shell.run: {exc.strerror or 'not found'}: {exc.filename or cwd}"
        ) from None
    except OSError as exc:
        raise ToolError(f"shell.run: {exc}") from None
