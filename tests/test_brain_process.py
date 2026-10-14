"""Tests for jarvis.brain.process.ClaudeProcess against a fake claude executable."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from jarvis.brain.failures import BrainUnavailable
from jarvis.brain.launch import LaunchSpec
from jarvis.brain.process import ClaudeProcess
from tests.brain_fakes import FakeClaude, process_gone, wait_until

Events = asyncio.Queue[dict[str, Any] | None]


@asynccontextmanager
async def running(fake: FakeClaude, cwd: Path) -> AsyncIterator[tuple[ClaudeProcess, Events]]:
    """A spawned fake claude and the queue its events land in; always killed on exit."""
    events: Events = asyncio.Queue()
    proc = await ClaudeProcess.spawn(
        LaunchSpec([fake.bin, "-p"], cwd, dict(os.environ)), events.put_nowait
    )
    try:
        yield proc, events
    finally:
        await proc.kill()


async def next_event(events: Events) -> dict[str, Any] | None:
    """The next event; the timeout only guards against a hung test."""
    return await asyncio.wait_for(events.get(), 10)


def test_should_emit_init_then_result_when_a_message_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClaude(tmp_path, monkeypatch, [[{"result": "hello"}]])

    async def main() -> None:
        async with running(fake, tmp_path) as (proc, events):
            await proc.send("hi")
            first, second = await next_event(events), await next_event(events)
            assert first is not None
            assert second is not None
            assert (first["type"], second["type"]) == ("system", "result")
            assert second["result"] == "hello"

    asyncio.run(main())


def test_should_deliver_unicode_verbatim_when_a_message_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "राहुल को लिखो"
    fake = FakeClaude(tmp_path, monkeypatch, [[{"result": "ok"}]])

    async def main() -> None:
        async with running(fake, tmp_path) as (proc, events):
            await proc.send(text)
            await next_event(events)
            await next_event(events)
            assert {"user": text} in fake.records()

    asyncio.run(main())


def test_should_skip_non_json_lines_when_stdout_has_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClaude(tmp_path, monkeypatch, [[{"noise": "not json"}, {"result": "ok"}]])

    async def main() -> None:
        async with running(fake, tmp_path) as (proc, events):
            await proc.send("hi")
            types = [(await next_event(events) or {}).get("type") for _ in range(2)]
            assert types == ["system", "result"]

    asyncio.run(main())


def test_should_signal_eof_and_not_be_alive_when_the_process_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClaude(tmp_path, monkeypatch, [[{"exit": 0}]])

    async def main() -> None:
        async with running(fake, tmp_path) as (proc, events):
            await proc.send("hi")
            first = await next_event(events)
            assert first is not None
            assert first["type"] == "system"
            assert await next_event(events) is None
            assert proc.alive is False

    asyncio.run(main())


def test_should_kill_the_whole_process_group_when_kill_is_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClaude(tmp_path, monkeypatch, [[{"result": "ok"}]], child=True)

    async def main() -> None:
        async with running(fake, tmp_path) as (proc, _):
            await wait_until(lambda: fake.child_pid() is not None)
            child = fake.child_pid()
            assert child is not None
            await proc.kill()
            assert process_gone(proc.pid)
            await wait_until(lambda: process_gone(child))
            assert proc.alive is False

    asyncio.run(main())


def test_should_not_raise_when_kill_is_called_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClaude(tmp_path, monkeypatch, [])

    async def main() -> None:
        async with running(fake, tmp_path) as (proc, _):
            await proc.kill()
            await proc.kill()

    asyncio.run(main())


def test_should_raise_brain_unavailable_when_the_executable_is_missing(tmp_path: Path) -> None:
    async def main() -> None:
        with pytest.raises(BrainUnavailable):
            await ClaudeProcess.spawn(LaunchSpec(["/nonexistent/claude"], tmp_path, {}), print)

    asyncio.run(main())
