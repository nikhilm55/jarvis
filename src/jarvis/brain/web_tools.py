"""Validate and route the brain's web tool call: `web.research` to the sealed researcher."""

import asyncio
from collections.abc import Mapping
from typing import Protocol

from jarvis.brain.failures import ToolError
from jarvis.web.errors import ResearchError

__all__ = ["MAX_REQUEST", "WebLike", "call_web"]

MAX_REQUEST = 1000  # characters: a question, not a document


class WebLike(Protocol):
    """The researcher surface the brain uses: a blocking run, done on a worker thread."""

    def research(self, request: str) -> dict[str, object]: ...


def _request(value: object) -> str:
    """Validate the request argument."""
    if not isinstance(value, str):
        raise ToolError("request must be a string")
    stripped = value.strip()
    if not stripped:
        raise ToolError("request must be non-empty")
    if len(stripped) > MAX_REQUEST:
        raise ToolError(f"request must be at most {MAX_REQUEST} characters")
    return stripped


async def call_web(web: WebLike, policy_name: str, args: Mapping[str, object]) -> dict[str, object]:
    """Validate one `web.*` call and run it on a worker thread; failures carry their code."""
    if policy_name != "web.research":
        raise ToolError(f"unknown web tool {policy_name}")
    if set(args) != {"request"}:
        raise ToolError("web.research: expected arguments request")
    request = _request(args["request"])
    try:
        return await asyncio.to_thread(web.research, request)
    except ResearchError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from None
    except OSError as exc:
        raise ToolError(f"INTERNAL: web.research could not start: {exc}") from None
