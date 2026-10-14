"""Reading Claude Code's stream-json events: tool-server health and the turn's result."""

import logging
from typing import Any

from jarvis.brain.failures import result_error_response
from jarvis.contract import FinalResponse, wrap_bare_text

_BAD_MCP = frozenset({"failed", "needs-auth", "disabled"})


def mcp_down(init_event: dict[str, Any]) -> bool:
    """True when the init event says Claude Code could not connect to Jarvis's tool server."""
    servers = init_event.get("mcp_servers")
    if not isinstance(servers, list):
        return False
    return any(
        isinstance(server, dict)
        and server.get("name") == "jarvis"
        and server.get("status") in _BAD_MCP
        for server in servers
    )


def result_response(
    event: dict[str, Any], assistant_error: str | None, log: logging.Logger
) -> FinalResponse:
    """Turn a `result` event into a response when the turn ended without a valid respond."""
    raw = event.get("result")
    text = raw if isinstance(raw, str) else ""
    if event.get("is_error"):
        log.warning("brain error result", extra={"assistant_error": assistant_error})
        return result_error_response(text, assistant_error)
    log.warning("contract violation", extra={"problems": ["no jarvis.respond call"]})  # FR-IO-06
    return wrap_bare_text(text)
