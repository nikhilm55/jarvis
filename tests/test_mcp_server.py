"""Tests for the jarvis.mcp.server MCP server: tool listing, auth and lifecycle."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from jarvis import policy
from jarvis.mcp.server import Dispatch, JarvisMcpServer
from jarvis.mcp.tools import TOOLS


@asynccontextmanager
async def _serving(
    dispatch: Dispatch, mode: policy.Mode = "balanced"
) -> AsyncIterator[JarvisMcpServer]:
    server = JarvisMcpServer(dispatch, lambda: mode)
    await server.start()
    try:
        yield server
    finally:
        await server.close()


@asynccontextmanager
async def _connected(server: JarvisMcpServer, mode: str = "auto") -> AsyncIterator[Client]:
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {server.token}"})
    async with (
        http,
        Client(streamable_http_client(server.url, http_client=http), mode=mode) as client,
    ):
        yield client


class _Recorder:
    def __init__(self, result: object = "done", error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.result = result
        self.error = error

    async def __call__(self, tool: str, args: dict[str, object]) -> object:
        self.calls.append((tool, args))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize("protocol", ["auto", "legacy"])
def test_should_list_tools_when_connected(protocol: str) -> None:
    async def scenario() -> None:
        async with _serving(_Recorder()) as server, _connected(server, protocol) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {t.name for t in TOOLS}
            for t in tools.tools:
                spec = next(x for x in TOOLS if x.name == t.name)
                assert t.description == spec.description
                assert t.input_schema == spec.input_schema

    asyncio.run(scenario())


def test_should_reject_auth_when_raw_http() -> None:
    async def scenario() -> None:
        async with _serving(_Recorder()) as server, httpx.AsyncClient() as http:
            r1 = await http.post(
                server.url, content=b"{}", headers={"Content-Type": "application/json"}
            )
            assert r1.status_code == 401
            r2 = await http.post(
                server.url,
                content=b"{}",
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
            )
            assert r2.status_code == 401
            r3 = await http.post(
                server.url,
                content=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {server.token}",
                    "Host": "evil.example",
                },
            )
            assert r3.status_code == 403

    asyncio.run(scenario())


def test_should_manage_lifecycle_when_started() -> None:
    async def scenario() -> None:
        rec = _Recorder()
        server = JarvisMcpServer(rec, lambda: "balanced")
        with pytest.raises(RuntimeError):
            _ = server.url
        with pytest.raises(RuntimeError):
            _ = server.token
        await server.start()
        assert server.url.startswith("http://127.0.0.1:")
        assert server.url.endswith("/mcp")
        with pytest.raises(RuntimeError):
            await server.start()
        await server.close()
        await server.close()
        with pytest.raises(httpx.ConnectError):
            async with httpx.AsyncClient() as http:
                await http.post(
                    server.url, content=b"{}", headers={"Content-Type": "application/json"}
                )

        s1 = JarvisMcpServer(_Recorder(), lambda: "balanced")
        s2 = JarvisMcpServer(_Recorder(), lambda: "balanced")
        await s1.start()
        await s2.start()
        try:
            assert s1.url != s2.url
            assert s1.token != s2.token
            assert len(s1.token) >= 32
        finally:
            await s1.close()
            await s2.close()

    asyncio.run(scenario())
