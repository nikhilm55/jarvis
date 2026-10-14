"""Tests for jarvis.hud.supervisor: the ways the HUD ends, stop(), and the window command."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from jarvis.hud.supervisor import window_spawner
from tests.hud_supervisor_rig import FakeProc, FakeSpawn, make_supervisor, until


def test_should_go_headless_with_warning_when_exit_no_gui() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            spawn.procs[0].finish(78)
            await supervisor.wait()
            assert spawn.count == 1
            assert supervisor.headless is True
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_go_headless_with_warning_when_exit_usage() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            spawn.procs[0].finish(2)
            await supervisor.wait()
            assert spawn.count == 1
            assert supervisor.headless is True
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_go_headless_with_warning_when_spawn_raises_file_not_found() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn(raises=FileNotFoundError("no interpreter"))
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await supervisor.wait()
            assert spawn.calls == 1
            assert supervisor.headless is True
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_not_restart_when_exit_zero() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            spawn.procs[0].finish(0)
            await supervisor.wait()
            assert spawn.count == 1
            assert supervisor.headless is False
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_kill_child_that_ignores_terminate_when_stopped() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn, stop_grace_s=0.01)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            spawn.procs[0].ignores_terminate = True
            await supervisor.stop()
            assert spawn.procs[0].killed is True
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_be_idempotent_and_raise_on_double_start() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.stop()
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            with pytest.raises(RuntimeError):
                await supervisor.start()
            await supervisor.stop()
            await supervisor.stop()
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_leave_no_task_behind_when_stopped() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        before = set(asyncio.all_tasks())
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            await supervisor.stop()
            after = set(asyncio.all_tasks())
            assert after - before == set()
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_build_correct_exec_call_when_window_spawner_invoked() -> None:
    async def scenario() -> None:
        recorded: dict[str, Any] = {}

        async def fake_exec(*args: Any, **kwargs: Any) -> FakeProc:
            recorded["args"] = args
            recorded["kwargs"] = kwargs
            return FakeProc()

        spawn = window_spawner(
            "python3", "http://localhost:8080", "secret-token", exec_fn=fake_exec
        )
        proc = await spawn()
        assert isinstance(proc, FakeProc)

        args = recorded["args"]
        kwargs = recorded["kwargs"]

        assert args[0] == "python3"
        assert args[1] == "-I"
        window_path = Path(args[2])
        assert window_path.exists()
        assert str(window_path).endswith("hud/window.py")
        assert args[3] == "--url"
        assert args[4] == "http://localhost:8080"

        env = kwargs["env"]
        assert env["JARVIS_HUD_TOKEN"] == "secret-token"  # noqa: S105
        assert "secret-token" not in args
        assert kwargs["stdin"] is asyncio.subprocess.DEVNULL

    asyncio.run(scenario())
