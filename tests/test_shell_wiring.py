"""The brain reaches run_shell only through the gate (R84 (g)), and the phrase tests (R106)."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from jarvis.brain.clock import TurnClock
from jarvis.brain.dispatch import TurnHooks, TurnTools
from jarvis.brain.failures import ToolError
from jarvis.brain.shell_tools import call_shell
from jarvis.policy.gated import tool_impl
from jarvis.shell import SHELL_TOOLS  # noqa: F401 - registers shell.run
from tests.gated_rig import Confirmer, dispatch


class FakeShell:
    """Records run calls; returns a canned result without touching the machine."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, float | None]] = []
        self.result = {"stdout": "ok\n", "stderr": "", "exit": 0, "timed_out": False}

    def run(
        self, cmd: str, cwd: str | None = None, timeout_s: float | None = None
    ) -> dict[str, object]:
        self.calls.append((cmd, cwd, timeout_s))
        return self.result


async def say(_text: str) -> None:
    return None


async def ask(_question: str, _options: list[str]) -> str:
    return ""


def test_should_route_shell_calls_to_the_run_shell_policy() -> None:
    shell = FakeShell()
    hooks = TurnHooks(say, ask, lambda _f: None, TurnClock())
    tools = TurnTools("t1", hooks, object(), 5, shell=shell)  # type: ignore[arg-type]
    asyncio.run(tools("shell.run", {"cmd": "echo hi"}))
    assert shell.calls == [("echo hi", None, None)]


def test_should_route_shell_calls_with_cwd_and_timeout() -> None:
    shell = FakeShell()
    hooks = TurnHooks(say, ask, lambda _f: None, TurnClock())
    tools = TurnTools("t1", hooks, object(), 5, shell=shell)  # type: ignore[arg-type]
    asyncio.run(tools("shell.run", {"cmd": "ls", "cwd": "~/Documents", "timeout_s": 10}))
    assert shell.calls == [("ls", "~/Documents", 10)]


@pytest.mark.parametrize(
    ("args", "expect"),
    [
        ({}, "cmd"),
        ({"cmd": ""}, "non-empty"),
        ({"cmd": "ls", "timeout_s": 0}, "1 to 300"),
        ({"cmd": "ls", "timeout_s": 301}, "1 to 300"),
        ({"cmd": "ls", "timeout_s": "60"}, "integer"),
        ({"cmd": "ls", "timeout_s": True}, "integer"),
        ({"cmd": "ls", "cwd": "x" * 1500}, "at most 1000"),
        ({"cmd": "ls", "cwd": "bad\x00path"}, "control characters"),
        ({"cmd": "ls", "extra": 1}, "expected"),
    ],
)
def test_should_refuse_bad_shell_args(args: dict[str, Any], expect: str) -> None:
    with pytest.raises(ToolError, match=expect):
        asyncio.run(call_shell(FakeShell(), "shell.run", args))


def test_should_refuse_an_unknown_shell_tool() -> None:
    with pytest.raises(ToolError, match="unknown shell tool"):
        asyncio.run(call_shell(FakeShell(), "shell.nope", {"cmd": "ls"}))


def test_should_refuse_shell_routing_without_a_shell() -> None:
    hooks = TurnHooks(say, ask, lambda _f: None, TurnClock())
    tools = TurnTools("t1", hooks, object(), 5)  # type: ignore[arg-type]
    with pytest.raises(ToolError, match=r"unknown tool shell\.run"):
        asyncio.run(tools("shell.run", {"cmd": "ls"}))


def test_should_reach_the_runner_through_the_gate_with_one_confirmation(
    tmp_path: Any,
) -> None:
    shell = FakeShell()

    @tool_impl("shell.run")
    async def impl(args: Mapping[str, object]) -> object:
        return await call_shell(shell, "shell.run", args)

    confirmer = Confirmer(yes=True)
    setup = {
        "cmd": f"mkdir -p {tmp_path}/demo && git init {tmp_path}/demo",
        "cwd": None,
        "timeout_s": None,
    }
    result, _, _ = dispatch("shell.run", setup, mode="balanced", confirmer=confirmer, impl=impl)
    assert result.error is None
    ask1 = len(confirmer.asked)
    result, _, _ = dispatch(
        "shell.run",
        {"cmd": "git status", "cwd": str(tmp_path / "demo")},
        mode="balanced",
        impl=impl,
    )
    if result.error is not None:
        raise AssertionError(f"T0 follow-up ran silently: {result.error}")
    ask2 = len(confirmer.asked)
    assert ask1 == 1 and ask2 == ask1  # R106: the set-up step asks once, then silent T0 steps
    assert len(shell.calls) == 2
    assert shell.calls[1][0] == "git status"
