import asyncio
import json
import logging

import httpx
import pytest

from jarvis.config import HudSettings
from jarvis.hud.runtime import running_hud
from jarvis.orchestrator.hud import HudEvent
from tests.hud_supervisor_rig import FakeSpawn, until


class RecordingSpawner:
    """Records spawner factory calls and returns a shared FakeSpawn."""

    def __init__(self) -> None:
        self.spawn = FakeSpawn()
        self.args: list[tuple[str, str, str]] = []

    def __call__(self, python: str, url: str, token: str) -> FakeSpawn:
        self.args.append((python, url, token))
        return self.spawn


class FailingServer:
    """A server whose start raises OSError."""

    def __init__(self, **_: object) -> None:
        return None

    async def start(self) -> None:
        raise OSError("port")


def test_should_yield_none_and_not_call_spawner_when_enabled_kwarg_is_false() -> None:
    async def scenario() -> None:
        spawner = RecordingSpawner()
        hud = HudSettings(python="/usr/bin/python3", enabled=True)
        async with running_hud(hud, enabled=False, spawner=spawner) as sink:
            assert sink is None
            assert spawner.args == []

    asyncio.run(scenario())


def test_should_yield_none_and_not_call_spawner_when_hud_setting_is_disabled() -> None:
    async def scenario() -> None:
        spawner = RecordingSpawner()
        hud = HudSettings(python="/usr/bin/python3", enabled=False)
        async with running_hud(hud, enabled=True, spawner=spawner) as sink:
            assert sink is None
            assert spawner.args == []

    asyncio.run(scenario())


def test_should_yield_sink_and_stream_event_when_enabled() -> None:
    async def scenario() -> None:
        spawner = RecordingSpawner()
        hud = HudSettings(python="/usr/bin/python3", enabled=True)
        async with running_hud(hud, enabled=True, spawner=spawner) as sink:
            assert spawner.args
            python, url, token = spawner.args[0]
            assert python == "/usr/bin/python3"
            assert url.startswith("http://127.0.0.1:")
            assert url.endswith("/hud")
            assert token
            await until(lambda: spawner.spawn.count == 1)
            assert sink is not None
            events_url = url[: -len("/hud")] + "/events"
            async with asyncio.timeout(5):
                async with (
                    httpx.AsyncClient() as client,
                    client.stream(
                        "GET",
                        events_url,
                        headers={"Authorization": f"Bearer {token}"},
                    ) as response,
                ):
                    lines = response.aiter_lines()
                    assert await anext(lines) == ": connected"
                    await sink(HudEvent("speaking", "hello"))
                    line = await anext(lines)
                    while not line.startswith("data: "):
                        line = await anext(lines)
                    payload = json.loads(line[len("data: ") :])
                    assert payload["state"] == "speaking"
                    assert payload["text"] == "hello"

    asyncio.run(scenario())


def test_should_terminate_window_and_close_server_when_context_exits() -> None:
    async def scenario() -> None:
        spawner = RecordingSpawner()
        hud = HudSettings(python="/usr/bin/python3", enabled=True)
        url = ""
        proc = None
        async with running_hud(hud, enabled=True, spawner=spawner):
            assert spawner.args
            _, url, _ = spawner.args[0]
            await until(lambda: spawner.spawn.count == 1)
            proc = spawner.spawn.procs[0]
        assert proc is not None
        assert proc.terminated is True
        with pytest.raises(httpx.ConnectError):
            async with asyncio.timeout(5):
                async with httpx.AsyncClient() as client:
                    await client.get(url)

    asyncio.run(scenario())


def test_should_terminate_window_when_body_raises() -> None:
    async def scenario() -> None:
        spawner = RecordingSpawner()
        hud = HudSettings(python="/usr/bin/python3", enabled=True)
        with pytest.raises(RuntimeError, match="boom"):
            async with running_hud(hud, enabled=True, spawner=spawner):
                await until(lambda: spawner.spawn.count == 1)
                raise RuntimeError("boom")
        assert spawner.spawn.procs[0].terminated is True

    asyncio.run(scenario())


def test_should_yield_none_and_log_warning_when_server_start_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("jarvis.hud.runtime.HudServer", FailingServer)

    async def scenario() -> None:
        spawner = RecordingSpawner()
        hud = HudSettings(python="/usr/bin/python3", enabled=True)
        async with running_hud(hud, enabled=True, spawner=spawner) as sink:
            assert sink is None
            assert spawner.args == []

    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
