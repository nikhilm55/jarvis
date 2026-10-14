"""Tests for the jarvis.mcp.server MCP server: gate, dispatch, auth and lifecycle."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent

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


def _text(result: CallToolResult) -> str:
    """The single text block of a tool result."""
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


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


@pytest.mark.parametrize("protocol", ["auto", "legacy"])
def test_should_return_volume_when_get(protocol: str) -> None:
    async def scenario() -> None:
        rec = _Recorder(result={"percent": 40, "muted": False})
        async with _serving(rec) as server, _connected(server, protocol) as client:
            res = await client.call_tool("volume_get", {})
            assert res.is_error is False
            assert json.loads(_text(res)) == {"percent": 40, "muted": False}
            assert rec.calls == [("desktop.volume_get", {})]

    asyncio.run(scenario())


def test_should_pass_args_when_say() -> None:
    async def scenario() -> None:
        rec = _Recorder(result="done")
        async with _serving(rec) as server, _connected(server) as client:
            res = await client.call_tool("say", {"text": "hi"})
            assert res.is_error is False
            assert _text(res) == "done"
            assert rec.calls == [("jarvis.say", {"text": "hi"})]

    asyncio.run(scenario())


def test_should_pass_raw_args_when_respond() -> None:
    async def scenario() -> None:
        rec = _Recorder(result="please fix X")
        async with _serving(rec) as server, _connected(server) as client:
            res = await client.call_tool("respond", {"status": "bogus"})
            assert res.is_error is False
            assert _text(res) == "please fix X"
            assert rec.calls == [("jarvis.respond", {"status": "bogus"})]

    asyncio.run(scenario())


def test_should_deny_when_safe_mode() -> None:
    async def scenario() -> None:
        rec = _Recorder()
        async with _serving(rec, mode="safe") as server, _connected(server) as client:
            res = await client.call_tool("open_app", {"name": "firefox"})
            assert res.is_error is True
            assert _text(res) == policy.NEEDS_CONFIRMATION_REASON
            assert rec.calls == []

    asyncio.run(scenario())


def test_should_gate_in_worker_when_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rec = _Recorder()
        gate_calls: list[tuple[str, dict[str, object], policy.Mode, bool]] = []

        def fake_gate(tool: str, args: dict[str, object], m: policy.Mode) -> policy.Decision:
            gate_calls.append(
                (tool, args, m, threading.current_thread() is not threading.main_thread())
            )
            return policy.Decision(True, "ok")

        monkeypatch.setattr(policy, "gate", fake_gate)
        async with _serving(rec, mode="yolo") as server, _connected(server) as client:
            res = await client.call_tool("mute", {"on": True})
            assert res.is_error is False
            assert rec.calls == [("desktop.mute", {"on": True})]
            assert gate_calls[0][0] == "desktop.mute"
            assert gate_calls[0][1] == {"on": True}
            assert gate_calls[0][2] == "yolo"
            assert gate_calls[0][3] is True

    asyncio.run(scenario())


def test_should_deny_when_gate_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rec = _Recorder()

        def fake_gate(tool: str, args: dict[str, object], m: policy.Mode) -> policy.Decision:
            return policy.Decision(False, "nope")

        monkeypatch.setattr(policy, "gate", fake_gate)
        async with _serving(rec, mode="yolo") as server, _connected(server) as client:
            res = await client.call_tool("mute", {"on": True})
            assert res.is_error is True
            assert _text(res) == "nope"
            assert rec.calls == []

    asyncio.run(scenario())


def test_should_error_when_unknown_tool() -> None:
    async def scenario() -> None:
        rec = _Recorder()
        async with _serving(rec) as server, _connected(server) as client:
            res = await client.call_tool("nope", {})
            assert res.is_error is True
            assert _text(res) == "unknown tool"
            assert rec.calls == []
            res2 = await client.call_tool("desktop.mute", {"on": True})
            assert res2.is_error is True
            assert _text(res2) == "unknown tool"
            assert rec.calls == []

    asyncio.run(scenario())


def test_should_keep_serving_when_dispatch_raises() -> None:
    async def scenario() -> None:
        calls = 0

        async def dispatch(tool: str, args: dict[str, object]) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")
            return "ok"

        async with _serving(dispatch) as server, _connected(server) as client:
            res = await client.call_tool("volume_get", {})
            assert res.is_error is True
            assert "RuntimeError" in _text(res)
            assert "boom" in _text(res)
            res2 = await client.call_tool("volume_get", {})
            assert res2.is_error is False
            assert _text(res2) == "ok"

    asyncio.run(scenario())


def test_should_mask_secrets_when_dispatch_raises() -> None:
    async def scenario() -> None:
        async with (
            _serving(_Recorder(error=ValueError("bad Bearer abcdefghij1234567890"))) as server,
            _connected(server) as client,
        ):
            res = await client.call_tool("volume_get", {})
            assert res.is_error is True
            assert "abcdefghij1234567890" not in _text(res)
            assert "Bearer ***" in _text(res)

    asyncio.run(scenario())


def test_should_deny_when_get_mode_raises() -> None:
    async def scenario() -> None:
        rec = _Recorder()

        def bad_mode() -> policy.Mode:
            raise RuntimeError("no mode")

        server = JarvisMcpServer(rec, bad_mode)
        await server.start()
        try:
            async with _connected(server) as client:
                res = await client.call_tool("volume_get", {})
                assert res.is_error is True
                assert rec.calls == []
        finally:
            await server.close()

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
