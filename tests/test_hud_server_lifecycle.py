"""Tests for jarvis.hud.server.HudServer: lifecycle, payloads, clients coming and going."""

import asyncio

import httpx
import pytest

from jarvis.hud.server import HudServer
from jarvis.orchestrator.hud import HudEvent
from tests.hud_rig import next_event, started, stream, until


def test_should_track_client_count_when_stream_open_and_closed() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            async with stream(server):
                assert server.client_count == 1
            await until(lambda: server.client_count == 0)
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_drop_slow_subscriber_when_queue_is_full() -> None:
    """A slow subscriber is dropped without blocking the publisher."""

    async def scenario() -> None:
        server = HudServer(queue_size=2)
        await server.start()
        try:
            slow = server.subscribe()
            fast = server.subscribe()

            for _ in range(3):
                await server.publish(HudEvent("idle"))
                fast.queue.get_nowait()

            assert slow.dropped is True
            assert fast.dropped is False
            assert server.client_count == 1
            assert slow.queue.get_nowait() is None
            assert slow.queue.empty()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_send_ping_when_keepalive_interval_elapsed() -> None:
    async def scenario() -> None:
        server = await started(keepalive_s=0.05)
        try:
            async with stream(server) as lines, asyncio.timeout(5):
                line = ""
                while not line:
                    line = await anext(lines)
            assert line == ": ping"
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_end_stream_when_server_closed() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            async with stream(server) as lines:
                await server.close()
                async with asyncio.timeout(5):
                    rest = [line async for line in lines if line.startswith("data:")]
            assert rest == []
            assert server.client_count == 0
            async with httpx.AsyncClient() as client:
                with pytest.raises(httpx.ConnectError):
                    await client.get(server.url)
            await server.close()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_leave_no_task_when_server_closed() -> None:
    """close() does not leave any new asyncio tasks behind."""

    async def scenario() -> None:
        before = set(asyncio.all_tasks())
        server = await started()
        try:
            pass
        finally:
            await server.close()

        after = set(asyncio.all_tasks())
        assert after - before == set()

    asyncio.run(scenario())


def test_should_round_trip_extra_and_non_ascii_when_event_published() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            async with stream(server) as lines:
                extra = {"level": 0.5, "options": ["a", "b"]}
                await server.publish(HudEvent("speaking", "caf\u00e9 \u2603", extra))
                payload = await next_event(lines)
            assert payload == {"state": "speaking", "text": "caf\u00e9 \u2603", "extra": extra}
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_raise_when_accessing_url_or_token_before_start() -> None:
    """url and token raise RuntimeError before start()."""
    server = HudServer()
    with pytest.raises(RuntimeError, match="server not started"):
        _ = server.url
    with pytest.raises(RuntimeError, match="server not started"):
        _ = server.token


def test_should_raise_when_start_called_twice() -> None:
    """A second start() raises RuntimeError."""

    async def scenario() -> None:
        server = await started()
        try:
            with pytest.raises(RuntimeError):
                await server.start()
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_not_raise_when_publish_before_start_or_after_close() -> None:
    """publish() is a no-op when not started or after close."""

    async def scenario() -> None:
        server = HudServer()
        await server.publish(HudEvent("idle"))

        await server.start()
        await server.close()
        await server.publish(HudEvent("idle"))

    asyncio.run(scenario())


def test_should_generate_unique_token_when_server_created() -> None:
    """Each server instance has a unique token of at least 32 chars."""

    async def scenario() -> None:
        server_a = await started()
        try:
            server_b = await started()
            try:
                assert server_a.token != server_b.token
                assert len(server_a.token) >= 32
                assert len(server_b.token) >= 32
            finally:
                await server_b.close()
        finally:
            await server_a.close()

    asyncio.run(scenario())
