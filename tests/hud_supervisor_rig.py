"""Fakes for the HUD supervisor tests: a process that exits on demand, spawn, sleep, clock."""

import asyncio
from collections.abc import Callable
from typing import Any

from jarvis.hud.supervisor import HudSupervisor


class FakeProc:
    def __init__(self, *, ignores_terminate: bool = False) -> None:
        self.ignores_terminate = ignores_terminate
        self.terminated = False
        self.killed = False
        self.returncode: int | None = None
        self._exit: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    def finish(self, code: int) -> None:
        self.returncode = code
        if not self._exit.done():
            self._exit.set_result(code)

    async def wait(self) -> int:
        return await asyncio.shield(self._exit)  # a cancelled waiter must not cancel the exit

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignores_terminate:
            self.finish(-15)

    def kill(self) -> None:
        self.killed = True
        self.finish(-9)


class FakeSpawn:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.procs: list[FakeProc] = []
        self.calls = 0
        self.raises = raises

    @property
    def count(self) -> int:
        return len(self.procs)

    async def __call__(self) -> FakeProc:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        proc = FakeProc()
        self.procs.append(proc)
        return proc


class FakeSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


class FakeClock:
    def __init__(self) -> None:
        self.now: float = 0.0

    def __call__(self) -> float:
        return self.now


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0)


async def crash(spawn: FakeSpawn, index: int) -> None:
    spawn.procs[index].finish(1)
    await until(lambda: spawn.count == index + 2)


def make_supervisor(spawn: FakeSpawn, **kwargs: Any) -> tuple[HudSupervisor, FakeSleep, FakeClock]:
    sleep = FakeSleep()
    clock = FakeClock()
    supervisor = HudSupervisor(spawn, sleep=sleep, clock=clock, **kwargs)
    return supervisor, sleep, clock
