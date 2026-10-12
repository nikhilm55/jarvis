"""Tests for the jarvis.mcp.guard ASGI middleware."""

import asyncio
from collections.abc import Mapping

import httpx
import pytest
from starlette.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send

from jarvis.mcp.guard import GuardMiddleware

TOKEN = "t0ken-for-tests-0123456789abcdef"  # noqa: S105
ALLOWED_HOSTS = frozenset({"127.0.0.1:8765", "localhost:8765"})


def _build(calls: list[str]) -> GuardMiddleware:
    """Build a GuardMiddleware wrapping a downstream app that records scope types."""

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(scope["type"])
        if scope["type"] == "http":
            await PlainTextResponse("ok")(scope, receive, send)

    return GuardMiddleware(downstream, token=TOKEN, allowed_hosts=ALLOWED_HOSTS)


async def _get(
    guarded: GuardMiddleware,
    headers: Mapping[str, str] | list[tuple[str, str]] | list[tuple[bytes, bytes]] | None = None,
    method: str = "GET",
) -> httpx.Response:
    """Send an HTTP request through the guarded app and return the response."""
    transport = httpx.ASGITransport(app=guarded)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
        return await client.request(method, "/", headers=headers)


def test_should_return_200_when_host_and_token_are_valid() -> None:
    """A valid host and Bearer token should reach the downstream app."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
        assert resp.text == "ok"
        assert calls == ["http"]

    asyncio.run(scenario())


def test_should_return_200_when_scheme_is_lowercase() -> None:
    """A lowercase 'bearer' scheme should be accepted."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": f"bearer {TOKEN}"})
        assert resp.status_code == 200
        assert calls == ["http"]

    asyncio.run(scenario())


def test_should_return_200_when_host_is_localhost() -> None:
    """Host 'localhost:8765' should be accepted."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(
            guarded,
            headers={"Host": "localhost:8765", "Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 200
        assert calls == ["http"]

    asyncio.run(scenario())


def test_should_return_200_when_host_is_uppercase() -> None:
    """Host 'LOCALHOST:8765' should be accepted after lower-casing."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(
            guarded,
            headers={"Host": "LOCALHOST:8765", "Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 200
        assert calls == ["http"]

    asyncio.run(scenario())


def test_should_return_401_when_authorization_is_missing() -> None:
    """A missing Authorization header should yield 401 with WWW-Authenticate."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded)
        assert resp.status_code == 401
        assert resp.headers["WWW-Authenticate"] == "Bearer"
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_token_is_wrong() -> None:
    """A wrong token should yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_scheme_is_basic() -> None:
    """A 'Basic' scheme should yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": f"Basic {TOKEN}"})
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_bearer_has_no_token() -> None:
    """A bare 'Bearer' header should yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": "Bearer"})
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_token_has_trailing_space() -> None:
    """A token with a trailing space should yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": f"Bearer {TOKEN} "})
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_token_has_extra_char() -> None:
    """A token with an extra character should yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Authorization": f"Bearer {TOKEN}x"})
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_credentials_are_non_ascii() -> None:
    """Non-ASCII credentials should yield 401 without raising."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers=[(b"Authorization", "Bearer \u00e9".encode("latin-1"))])
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_401_when_two_authorization_headers_are_present() -> None:
    """Duplicate Authorization headers should yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(
            guarded,
            headers=[
                ("Authorization", f"Bearer {TOKEN}"),
                ("Authorization", "Bearer wrong"),
            ],
        )
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_return_403_when_host_is_evil() -> None:
    """An untrusted host should yield 403 even with a valid token."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(
            guarded,
            headers={"Host": "evil.example", "Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 403
        assert calls == []

    asyncio.run(scenario())


def test_should_return_403_when_host_port_is_wrong() -> None:
    """A wrong port in the Host header should yield 403."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(
            guarded,
            headers={"Host": "127.0.0.1:9999", "Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 403
        assert calls == []

    asyncio.run(scenario())


def test_should_return_403_when_two_host_headers_are_present() -> None:
    """Duplicate Host headers should yield 403."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(
            guarded,
            headers=[
                ("Host", "127.0.0.1:8765"),
                ("Host", "evil.example"),
                ("Authorization", f"Bearer {TOKEN}"),
            ],
        )
        assert resp.status_code == 403
        assert calls == []

    asyncio.run(scenario())


def test_should_return_403_when_host_is_bad_and_token_is_missing() -> None:
    """A bad host should yield 403 even without a token (host checked first)."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, headers={"Host": "evil.example"})
        assert resp.status_code == 403
        assert calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_should_return_401_for_every_method_when_token_is_missing(method: str) -> None:
    """GET, POST and DELETE without a token should all yield 401."""
    calls: list[str] = []
    guarded = _build(calls)

    async def scenario() -> None:
        resp = await _get(guarded, method=method)
        assert resp.status_code == 401
        assert calls == []

    asyncio.run(scenario())


def test_should_pass_lifespan_scope_to_downstream() -> None:
    """A lifespan scope should be passed straight to the wrapped app."""
    calls: list[str] = []
    guarded = _build(calls)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        pass

    asyncio.run(guarded({"type": "lifespan"}, receive, send))
    assert calls == ["lifespan"]


def test_should_close_websocket_scope_with_1008() -> None:
    """A websocket scope should be rejected with a websocket.close 1008 message."""
    calls: list[str] = []
    guarded = _build(calls)
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "websocket.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(guarded({"type": "websocket"}, receive, send))
    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert calls == []


def test_should_refuse_to_build_when_token_is_empty() -> None:
    """An empty token would make "Bearer " valid, so construction must fail."""

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        pass

    with pytest.raises(ValueError, match="token"):
        GuardMiddleware(downstream, token="", allowed_hosts=ALLOWED_HOSTS)
