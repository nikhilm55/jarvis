"""ASGI middleware guarding the loopback MCP endpoint."""

import hmac

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from jarvis.log import get_logger


def _single_header(scope: Scope, name: bytes) -> bytes | None:
    """Return the value of a header present exactly once, else None."""
    values: list[bytes] = [value for header_name, value in scope["headers"] if header_name == name]
    if len(values) != 1:
        return None
    return values[0]


class GuardMiddleware:
    """Auth + DNS-rebinding guard in front of the MCP app.

    Host is checked first, then the bearer token; every HTTP method is covered.
    Paths in open_paths skip the token check only; the Host check still applies.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        allowed_hosts: frozenset[str],
        open_paths: frozenset[str] = frozenset(),
    ) -> None:
        """Store the app, expected token bytes, allowed hosts, open paths, and logger."""
        if not token:
            raise ValueError("token must be non-empty")
        self._app = app
        self._expected = token.encode("utf-8")
        self._allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self._open_paths = open_paths
        self._log = get_logger("mcp.guard")

    def _token_ok(self, value: bytes | None) -> bool:
        """Return True only for a well-formed bearer token matching the secret."""
        if value is None:
            return False
        scheme, separator, credentials = value.partition(b" ")
        return (
            scheme.lower() == b"bearer"
            and separator != b""
            and hmac.compare_digest(credentials, self._expected)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Dispatch lifespan, reject non-http, then enforce host and token."""
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        host = _single_header(scope, b"host")
        if host is None or host.decode("latin-1").lower() not in self._allowed_hosts:
            self._log.warning("rejected request: bad host")
            await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
            return
        if scope["path"] in self._open_paths:
            await self._app(scope, receive, send)
            return
        auth = _single_header(scope, b"authorization")
        if not self._token_ok(auth):
            self._log.warning("rejected request: bad token")
            await PlainTextResponse(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        await self._app(scope, receive, send)
