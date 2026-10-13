"""Helpers for the HUD server tests: start a real server, read its SSE stream."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from jarvis.hud.server import HudServer


async def started(*, queue_size: int = 64, keepalive_s: float = 15.0) -> HudServer:
    """Create, start and return a HudServer."""
    server = HudServer(queue_size=queue_size, keepalive_s=keepalive_s)
    await server.start()
    return server


async def until(predicate: Callable[[], bool]) -> None:
    """Sleep until predicate is true, with a timeout."""
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


def events_url(server: HudServer) -> str:
    """Return the /events URL of a started server."""
    return server.url.removesuffix("/hud") + "/events"


@contextlib.asynccontextmanager
async def stream(server: HudServer) -> AsyncIterator[AsyncIterator[str]]:
    """Open /events with the token and yield its lines after the `: connected` greeting."""
    auth = {"Authorization": f"Bearer {server.token}"}
    async with (
        httpx.AsyncClient() as client,
        client.stream("GET", events_url(server), headers=auth) as response,
    ):
        lines = response.aiter_lines()
        async with asyncio.timeout(5):
            assert await anext(lines) == ": connected"
        yield lines


async def next_event(lines: AsyncIterator[str]) -> dict[str, Any]:
    """Return the next `data:` message as a dict."""
    async with asyncio.timeout(5):
        while True:
            line = await anext(lines)
            if line.startswith("data: "):
                payload: dict[str, Any] = json.loads(line.removeprefix("data: "))
                return payload
