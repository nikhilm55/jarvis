"""Tests for jarvis.hud.server.HudServer: routes, auth and event delivery."""

import asyncio

import httpx

from jarvis.hud.page import read_page
from jarvis.orchestrator.hud import HudEvent
from tests.hud_rig import next_event, started, stream


def test_should_serve_page_when_client_requests_hud() -> None:
    """GET /hud returns the page with CSP header and no auth."""

    async def scenario() -> None:
        server = await started()
        try:
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    response = await client.get(server.url)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/html")
            assert response.text == read_page()
            assert "content-security-policy" in response.headers
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_return_401_when_events_requested_without_valid_token() -> None:
    """GET /events returns 401 without auth or with wrong token."""

    async def scenario() -> None:
        server = await started()
        try:
            events_url = server.url.removesuffix("/hud") + "/events"
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    response_no_auth = await client.get(events_url)
                assert response_no_auth.status_code == 401

                async with asyncio.timeout(5):
                    response_wrong = await client.get(
                        events_url,
                        headers={"Authorization": "Bearer wrong-token"},
                    )
                assert response_wrong.status_code == 401
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_return_403_when_host_header_is_not_loopback() -> None:
    """GET /events and /hud return 403 for non-loopback Host headers."""

    async def scenario() -> None:
        server = await started()
        try:
            events_url = server.url.removesuffix("/hud") + "/events"
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    response_events = await client.get(
                        events_url,
                        headers={"Host": "evil.example"},
                    )
                assert response_events.status_code == 403

                async with asyncio.timeout(5):
                    response_hud = await client.get(
                        server.url,
                        headers={"Host": "evil.example"},
                    )
                assert response_hud.status_code == 403
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_receive_events_in_order_when_client_is_connected() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            async with stream(server) as lines:
                sent = [
                    HudEvent("listening", "one"),
                    HudEvent("transcript", "two"),
                    HudEvent("speaking", "3"),
                ]
                for event in sent:
                    await server.publish(event)
                received = [await next_event(lines) for _ in range(3)]
            assert [(e["state"], e["text"]) for e in received] == [
                ("listening", "one"),
                ("transcript", "two"),
                ("speaking", "3"),
            ]
        finally:
            await server.close()

    asyncio.run(scenario())
