"""Tests for GuardMiddleware open_paths keyword."""

import asyncio

import httpx
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from jarvis.mcp.guard import GuardMiddleware

TOKEN = "t0ken-for-tests-0123456789abcdef"  # noqa: S105
ALLOWED_HOSTS = frozenset({"127.0.0.1:8765", "localhost:8765"})


def _make_downstream(calls: list[Scope]) -> ASGIApp:
    """Build an ASGI app that records scope and answers 200 ok."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(scope)
        if scope["type"] == "http":
            response = PlainTextResponse("ok")
            await response(scope, receive, send)

    return app


def _build_guarded(calls: list[Scope], open_paths: frozenset[str] | None = None) -> GuardMiddleware:
    """Build a GuardMiddleware-wrapped app with the given open paths."""
    downstream = _make_downstream(calls)
    if open_paths is None:
        return GuardMiddleware(downstream, token=TOKEN, allowed_hosts=ALLOWED_HOSTS)
    return GuardMiddleware(
        downstream,
        token=TOKEN,
        allowed_hosts=ALLOWED_HOSTS,
        open_paths=open_paths,
    )


async def _get(
    guarded: GuardMiddleware, path: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    """Send a GET request through the guarded ASGI app."""
    transport = httpx.ASGITransport(app=guarded)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
        return await client.request("GET", path, headers=headers or {})


def test_should_return_200_when_open_path_without_auth() -> None:
    """GET /hud with no Authorization returns 200 and calls downstream."""
    calls: list[Scope] = []
    guarded = _build_guarded(calls, open_paths=frozenset({"/hud"}))

    async def scenario() -> httpx.Response:
        return await _get(guarded, "/hud")

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert response.text == "ok"
    assert len(calls) == 1


def test_should_return_401_when_non_open_path_without_auth() -> None:
    """GET /events with no Authorization returns 401 and skips downstream."""
    calls: list[Scope] = []
    guarded = _build_guarded(calls, open_paths=frozenset({"/hud"}))

    async def scenario() -> httpx.Response:
        return await _get(guarded, "/events")

    response = asyncio.run(scenario())
    assert response.status_code == 401
    assert len(calls) == 0


def test_should_return_403_when_open_path_with_disallowed_host() -> None:
    """GET /hud with disallowed Host returns 403 and skips downstream."""
    calls: list[Scope] = []
    guarded = _build_guarded(calls, open_paths=frozenset({"/hud"}))

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=guarded)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://evil.example:8765"
        ) as client:
            return await client.request("GET", "/hud")

    response = asyncio.run(scenario())
    assert response.status_code == 403
    assert len(calls) == 0


def test_should_return_401_when_path_starts_with_open_path() -> None:
    """GET /hud/extra (longer path) with no Authorization returns 401."""
    calls: list[Scope] = []
    guarded = _build_guarded(calls, open_paths=frozenset({"/hud"}))

    async def scenario() -> httpx.Response:
        return await _get(guarded, "/hud/extra")

    response = asyncio.run(scenario())
    assert response.status_code == 401
    assert len(calls) == 0


def test_should_return_401_when_default_middleware_without_auth() -> None:
    """GET /hud with default middleware (no open_paths) returns 401."""
    calls: list[Scope] = []
    guarded = _build_guarded(calls)

    async def scenario() -> httpx.Response:
        return await _get(guarded, "/hud")

    response = asyncio.run(scenario())
    assert response.status_code == 401
    assert len(calls) == 0
