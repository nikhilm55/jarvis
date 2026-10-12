"""A running brain wired to the real MCP server and a fake claude, for session tests."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jarvis.brain.session import ClaudeCodeBrain
from jarvis.config import BrainSettings, Settings
from jarvis.contract import FinalResponse
from jarvis.mcp import JarvisMcpServer
from tests.brain_fakes import FakeClaude, envelope, wait_until


def fake_env() -> dict[str, str]:
    """The FAKE_CLAUDE_* variables the fake needs; the brain env is otherwise allowlisted."""
    return {k: v for k, v in os.environ.items() if k.startswith("FAKE_CLAUDE_")}


class FakeDesktop:
    """A fake desktop client that records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def _record(self, *call: object) -> dict[str, object]:
        self.calls.append(call)
        return {"app": call[1]} if call[0] == "open_app" else {"ok": True}

    async def open_app(self, query: str) -> dict[str, object]:
        return await self._record("open_app", query)

    async def close_app(self, query: str) -> dict[str, object]:
        return await self._record("close_app", query)

    async def volume_get(self) -> dict[str, object]:
        return await self._record("volume_get")

    async def volume_set(self, pct: int) -> dict[str, object]:
        return await self._record("volume_set", pct)

    async def volume_step(self, delta: int) -> dict[str, object]:
        return await self._record("volume_step", delta)

    async def mute(self, on: bool) -> dict[str, object]:
        return await self._record("mute", on)


class Callbacks:
    """Records what the brain says and asks; every question is answered "blue"."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.asked: list[tuple[str, list[str]]] = []

    async def on_say(self, text: str) -> None:
        self.said.append(text)

    async def on_ask(self, question: str, options: list[str]) -> str:
        self.asked.append((question, options))
        return "blue"


@dataclass
class Rig:
    """A running brain rig with desktop and callbacks."""

    brain: ClaudeCodeBrain
    desktop: FakeDesktop
    cb: Callbacks

    async def turn(self, command: str = "open calculator", turn_id: str = "t1") -> FinalResponse:
        """Run one brain turn."""
        return await self.brain.turn(envelope(command, turn_id), self.cb.on_say, self.cb.on_ask)


@asynccontextmanager
async def running_brain(fake: FakeClaude, **brain: Any) -> AsyncIterator[Rig]:
    """Yield a running brain rig, cleaning up on exit."""
    settings = Settings(brain=BrainSettings(**{"claude_bin": fake.bin, **brain}))
    desktop = FakeDesktop()
    holder: list[ClaudeCodeBrain] = []

    async def dispatch(name: str, args: dict[str, object]) -> object:
        return await holder[0].dispatch(name, args)  # the brain exists once the server is up

    server = JarvisMcpServer(dispatch, lambda: "balanced")
    await server.start()
    brain_obj = ClaudeCodeBrain(settings, server, desktop, extra_env=fake_env())
    holder.append(brain_obj)
    try:
        yield Rig(brain=brain_obj, desktop=desktop, cb=Callbacks())
    finally:
        await brain_obj.close()
        await server.close()


def play(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    turns: list[list[dict[str, Any]]],
    count: int = 1,
    **brain: Any,
) -> tuple[list[FinalResponse], Rig, FakeClaude]:
    """Run `count` sequential turns of a fake-claude scenario; return what the tests inspect."""
    fake = FakeClaude(tmp_path, monkeypatch, turns)

    async def main() -> tuple[list[FinalResponse], Rig]:
        async with running_brain(fake, **brain) as rig:
            responses = [await rig.turn(turn_id=f"t{n}") for n in range(1, count + 1)]
            # The brain returns when respond succeeds; let the fake finish logging its turn.
            await wait_until(lambda: sum("turn_done" in r for r in fake.records()) >= count)
            return responses, rig

    responses, rig = asyncio.run(main())
    return responses, rig, fake


VALID: dict[str, object] = {"status": "success", "spoken": "Done."}
INVALID: dict[str, object] = {"status": "bogus", "spoken": "x"}
Action = dict[str, Any]


def respond(args: dict[str, object] = VALID) -> Action:
    """A scenario action: the fake brain calls `respond` with `args`."""
    return {"call": "respond", "args": args}


def finish(*calls: Action) -> list[Action]:
    """A scenario turn: the given actions, then the trailing text and result events."""
    return [*calls, {"text": "Done."}, {"result": "Done."}]
