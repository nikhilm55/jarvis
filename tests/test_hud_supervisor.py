"""Tests for jarvis.hud.supervisor: spawning, restart backoff and the crash budget."""

import asyncio

from tests.hud_supervisor_rig import FakeSpawn, crash, make_supervisor, until


def test_should_spawn_one_process_and_terminate_on_stop_when_started() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            await supervisor.stop()
            assert spawn.procs[0].terminated is True
            assert supervisor.headless is False
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_restart_with_backoff_when_crashed() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, sleep, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            spawn.procs[0].finish(1)
            await until(lambda: spawn.count == 2)
            assert sleep.delays == [0.5]

            spawn.procs[1].finish(1)
            await until(lambda: spawn.count == 3)
            assert sleep.delays == [0.5, 1.0]
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_restart_with_capped_backoff_when_crashed_four_times() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, sleep, _ = make_supervisor(spawn, max_crashes=10)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            for i in range(4):
                await crash(spawn, i)
            assert sleep.delays == [0.5, 1.0, 2.0, 2.0]
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_go_headless_when_crashed_more_than_max_within_window() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, _ = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            for i in range(3):
                await crash(spawn, i)
            spawn.procs[3].finish(1)  # the fourth crash within the window: give up
            async with asyncio.timeout(5):
                await supervisor.wait()
            assert spawn.count == 4
            assert supervisor.headless is True
        finally:
            await supervisor.stop()

    asyncio.run(scenario())


def test_should_not_accumulate_crashes_when_spread_beyond_window() -> None:
    async def scenario() -> None:
        spawn = FakeSpawn()
        supervisor, _, clock = make_supervisor(spawn)
        try:
            await supervisor.start()
            await until(lambda: spawn.count == 1)
            for i in range(5):
                await crash(spawn, i)
                clock.now += 100
            assert spawn.count == 6
            assert supervisor.headless is False
        finally:
            await supervisor.stop()

    asyncio.run(scenario())
