"""Loopback events API for the Jarvis HUD."""

import asyncio
import json
import secrets
import socket
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response, StreamingResponse
from starlette.routing import Route

from jarvis.hud.page import read_page
from jarvis.log import get_logger
from jarvis.mcp.guard import GuardMiddleware
from jarvis.mcp.server import EmbeddedServer
from jarvis.orchestrator.hud import HudEvent

logger = get_logger("hud")

FONT_ROUTE = "/fonts/InterVariable.woff2"
FONT_PATH = Path(__file__).with_name("fonts") / "InterVariable.woff2"


@dataclass(eq=False)
class Subscriber:
    """One connected /events client."""

    queue: asyncio.Queue[bytes | None]
    dropped: bool = False


class HudServer:
    """Loopback events API for the Jarvis HUD."""

    def __init__(self, *, queue_size: int = 64, keepalive_s: float = 15.0) -> None:
        """Create the server with the given queue size and keepalive interval."""
        self._queue_size = queue_size
        self._keepalive_s = keepalive_s
        self._subscribers: set[Subscriber] = set()
        self._server: EmbeddedServer | None = None
        self._task: asyncio.Task[None] | None = None
        self._token: str | None = None
        self._url: str | None = None
        self._closed = False
        self._warned_unencodable = False

    @property
    def url(self) -> str:
        """Return the HUD base URL; raise before start()."""
        if self._url is None:
            raise RuntimeError("server not started")
        return self._url

    @property
    def token(self) -> str:
        """Return the bearer token; raise before start()."""
        if self._token is None:
            raise RuntimeError("server not started")
        return self._token

    @property
    def client_count(self) -> int:
        """Return the number of active subscribers."""
        return len(self._subscribers)

    async def start(self) -> None:
        """Bind a loopback socket and start the embedded uvicorn server."""
        if self._task is not None:
            raise RuntimeError("server already started")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        token = secrets.token_urlsafe(32)
        hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
        app = Starlette(
            routes=[
                Route("/hud", self._page),
                Route("/events", self._events),
                Route(FONT_ROUTE, self._font),
            ]
        )
        guarded = GuardMiddleware(
            app,
            token=token,
            allowed_hosts=frozenset(hosts),
            open_paths=frozenset({"/hud", FONT_ROUTE}),
        )
        config = uvicorn.Config(
            guarded,
            log_config=None,
            log_level="warning",
            access_log=False,
            server_header=False,
            lifespan="off",
            timeout_graceful_shutdown=2,
        )
        server = EmbeddedServer(config)
        self._server = server
        self._task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            await self._wait_started(server, self._task)
        except BaseException:
            server.should_exit = True
            self._task.cancel()
            sock.close()
            raise
        self._token = token
        self._url = f"http://127.0.0.1:{port}/hud"

    async def _wait_started(self, server: EmbeddedServer, task: asyncio.Task[None]) -> None:
        """Wait until the server is started or the task fails."""
        deadline = time.monotonic() + 10.0
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("server stopped during startup")
            if time.monotonic() >= deadline:
                raise TimeoutError("server did not start")
            await asyncio.sleep(0.01)

    async def close(self) -> None:
        """Gracefully stop the server; idempotent and non-restartable."""
        if self._closed:
            return
        if self._server is None or self._task is None:
            return
        self._closed = True
        for subscriber in list(self._subscribers):
            self._end(subscriber)
        self._subscribers.clear()
        self._server.should_exit = True
        await self._task

    async def publish(self, event: HudEvent) -> None:
        """Fan out an event to every subscriber; never raises."""
        if self._server is None or self._closed:
            return
        try:
            payload = json.dumps(
                {"state": event.state, "text": event.text, "extra": event.extra},
                default=str,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            if not self._warned_unencodable:
                self._warned_unencodable = True
                logger.warning("HUD event is not JSON-serialisable; dropped")
            return
        message = b"data: " + payload.encode("utf-8") + b"\n\n"
        for subscriber in list(self._subscribers):
            try:
                subscriber.queue.put_nowait(message)
            except asyncio.QueueFull:
                self._drop(subscriber)
        await asyncio.sleep(0)

    def subscribe(self) -> Subscriber:
        """Create a new subscriber and register it."""
        subscriber = Subscriber(asyncio.Queue(maxsize=self._queue_size))
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        """Remove a subscriber from the registry."""
        self._subscribers.discard(subscriber)

    def _drop(self, subscriber: Subscriber) -> None:
        """Mark a subscriber as dropped and end its stream."""
        subscriber.dropped = True
        self._subscribers.discard(subscriber)
        self._drain(subscriber)
        subscriber.queue.put_nowait(None)
        logger.warning("subscriber dropped; queue full")

    def _end(self, subscriber: Subscriber) -> None:
        """Drain a subscriber's queue and send the sentinel."""
        self._drain(subscriber)
        subscriber.queue.put_nowait(None)

    def _drain(self, subscriber: Subscriber) -> None:
        """Remove all pending items from a subscriber's queue."""
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()

    async def _page(self, request: Request) -> HTMLResponse:
        """Serve the HUD page with security headers."""
        return HTMLResponse(
            read_page(),
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "script-src 'unsafe-inline'; connect-src 'self'; "
                    "font-src 'self'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    async def _font(self, request: Request) -> Response:
        """Serve the bundled Inter font with immutable cache headers."""
        return Response(
            await asyncio.to_thread(FONT_PATH.read_bytes),
            media_type="font/woff2",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _events(self, request: Request) -> StreamingResponse:
        """Stream server-sent events to a subscriber."""
        subscriber = self.subscribe()
        return StreamingResponse(
            self._stream(subscriber),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    async def _stream(self, subscriber: Subscriber) -> AsyncIterator[bytes]:
        """Yield SSE frames for a subscriber until it ends."""
        try:
            yield b": connected\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(subscriber.queue.get(), self._keepalive_s)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if item is None:
                    return
                yield item
        finally:
            self.unsubscribe(subscriber)
