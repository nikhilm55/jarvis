import asyncio
import json
import logging
import pathlib

import pytest

from jarvis.hud.server import HudServer
from jarvis.orchestrator.hud import HudEvent


def test_should_drop_event_when_extra_contains_nan() -> None:
    async def scenario() -> None:
        server = HudServer()
        try:
            await server.start()
            sub = server.subscribe()
            await server.publish(HudEvent("speaking", "x", {"level": float("nan")}))
            assert sub.queue.empty()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_drop_event_when_extra_contains_inf() -> None:
    async def scenario() -> None:
        server = HudServer()
        try:
            await server.start()
            sub = server.subscribe()
            await server.publish(HudEvent("speaking", "x", {"level": float("inf")}))
            assert sub.queue.empty()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_log_single_warning_when_multiple_bad_events_arrive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    async def scenario() -> None:
        server = HudServer()
        try:
            await server.start()
            await server.publish(HudEvent("speaking", "x", {"level": float("nan")}))
            await server.publish(HudEvent("speaking", "y", {"level": float("inf")}))
        finally:
            await server.close()

    asyncio.run(scenario())

    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_should_deliver_good_event_when_published_after_bad_one() -> None:
    async def scenario() -> None:
        server = HudServer()
        try:
            await server.start()
            sub = server.subscribe()
            await server.publish(HudEvent("speaking", "x", {"level": float("nan")}))
            await server.publish(HudEvent("idle", "hello", {}))
            item = await sub.queue.get()
            assert item is not None
            payload = json.loads(item.removeprefix(b"data: ").decode())
            assert payload["state"] == "idle"
            assert payload["text"] == "hello"
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_render_path_object_as_string_when_extra_holds_non_json_native() -> None:
    async def scenario() -> None:
        server = HudServer()
        try:
            await server.start()
            sub = server.subscribe()
            path = pathlib.PurePosixPath("/srv/x")
            await server.publish(HudEvent("speaking", "x", {"path": path}))
            item = await sub.queue.get()
            assert item is not None
            payload = json.loads(item.removeprefix(b"data: ").decode())
            assert payload["extra"]["path"] == "/srv/x"
        finally:
            await server.close()

    asyncio.run(scenario())
