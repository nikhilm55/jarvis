"""jarvisd's MCP server: loopback streamable HTTP over uvicorn with policy gating."""

import asyncio
import contextlib
import secrets
import socket
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import mcp_types as types
import uvicorn
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings

from jarvis import policy
from jarvis.log import get_logger
from jarvis.mcp.guard import GuardMiddleware
from jarvis.mcp.tools import SERVER_NAME, TOOLS

Dispatch = Callable[[str, dict[str, object]], Awaitable[object]]


class _EmbeddedServer(uvicorn.Server):
    """uvicorn server that leaves the host process's signal handlers alone."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        """Yield without installing signal handlers."""
        yield


class JarvisMcpServer:
    """One instance serves once; no module-level state."""

    def __init__(self, dispatch: Dispatch, get_mode: Callable[[], policy.Mode]) -> None:
        """Store the dispatch callable and mode provider for later use."""
        self._dispatch = dispatch
        self._get_mode = get_mode
        self._token: str | None = None
        self._url: str | None = None
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._log = get_logger("mcp")

    @property
    def url(self) -> str:
        """Return the MCP endpoint URL, raising if not started."""
        if self._url is None:
            raise RuntimeError("server not started")
        return self._url

    @property
    def token(self) -> str:
        """Return the bearer token, raising if not started."""
        if self._token is None:
            raise RuntimeError("server not started")
        return self._token

    async def start(self) -> None:
        """Bind a loopback socket and start the embedded uvicorn server."""
        if self._task is not None:
            raise RuntimeError("server already started")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        token = secrets.token_urlsafe(32)
        hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
        transport = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[f"http://{h}" for h in hosts],
        )
        lowlevel = Server(
            SERVER_NAME,
            on_list_tools=self._list_tools,
        )
        app = lowlevel.streamable_http_app(
            streamable_http_path="/mcp",
            transport_security=transport,
        )
        guarded = GuardMiddleware(app, token=token, allowed_hosts=frozenset(hosts))
        config = uvicorn.Config(
            guarded,
            log_config=None,
            log_level="warning",
            access_log=False,
            server_header=False,
            lifespan="on",
            timeout_graceful_shutdown=2,
        )
        server = _EmbeddedServer(config)
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
        self._url = f"http://127.0.0.1:{port}/mcp"

    async def _wait_started(self, server: uvicorn.Server, task: asyncio.Task[None]) -> None:
        """Wait until the server is listening, raising on failure or timeout."""
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
        self._server.should_exit = True
        await self._task

    async def _list_tools(
        self,
        ctx: ServerRequestContext[Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        """Return the registered MCP tools."""
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=t.name,
                    description=t.description,
                    input_schema=t.input_schema,
                )
                for t in TOOLS
            ]
        )
