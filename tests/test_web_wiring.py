"""The brain reaches the web through the gate like the other tools, and is never asked first."""

import asyncio

import pytest

from jarvis.brain.clock import TurnClock
from jarvis.brain.dispatch import TurnHooks, TurnTools
from jarvis.brain.failures import ToolError
from jarvis.brain.web_tools import MAX_REQUEST, call_web
from jarvis.policy import ToolCall, TurnContext
from jarvis.policy.decide import decide
from jarvis.web import WEB_TOOLS  # noqa: F401 - registers the web tool's policy
from jarvis.web.errors import ResearchError


class FakeWeb:
    """Records each request without touching the network."""

    def __init__(self, error: ResearchError | None = None) -> None:
        self.requests: list[str] = []
        self._error = error

    def research(self, request: str) -> dict[str, object]:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return {"answer": f"answer to {request}", "truncated": False}


async def say(_text: str) -> None:
    return None


async def ask(_question: str, _options: list[str]) -> str:
    return ""


def _tools(web: FakeWeb | None) -> TurnTools:
    hooks = TurnHooks(say, ask, lambda _f: None, TurnClock())
    return TurnTools("t1", hooks, object(), 5, web=web)  # type: ignore[arg-type]


def test_should_route_web_research_to_the_researcher() -> None:
    web = FakeWeb()
    out = asyncio.run(_tools(web)("web.research", {"request": " best credit card deals India "}))
    assert web.requests == ["best credit card deals India"]
    assert out == {"answer": "answer to best credit card deals India", "truncated": False}


@pytest.mark.parametrize("mode", ["safe", "balanced", "yolo"])
def test_should_run_web_research_without_asking_in_every_mode(mode: str) -> None:
    call = ToolCall("web.research", {"request": "best credit card deals in India"}, "brain")
    decision = decide(call, mode, TurnContext("t", mode=mode))  # type: ignore[arg-type]
    assert decision.action == "run"
    assert decision.scopes == ()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({}, "expected arguments request"),
        ({"request": "x", "url": "https://a.b"}, "expected arguments request"),
        ({"request": 42}, "must be a string"),
        ({"request": "   "}, "non-empty"),
        ({"request": "x" * (MAX_REQUEST + 1)}, f"at most {MAX_REQUEST}"),
    ],
)
def test_should_refuse_bad_arguments(args: dict[str, object], message: str) -> None:
    web = FakeWeb()
    with pytest.raises(ToolError, match=message):
        asyncio.run(call_web(web, "web.research", args))
    assert web.requests == []


def test_should_turn_a_research_failure_into_a_coded_tool_error() -> None:
    web = FakeWeb(ResearchError("TIMEOUT", "the web search took longer than 90 seconds"))
    with pytest.raises(ToolError, match=r"^TIMEOUT: the web search took longer"):
        asyncio.run(call_web(web, "web.research", {"request": "slow"}))


def test_should_refuse_web_routing_without_the_researcher() -> None:
    with pytest.raises(ToolError, match=r"unknown tool web\.research"):
        asyncio.run(_tools(None)("web.research", {"request": "news"}))
