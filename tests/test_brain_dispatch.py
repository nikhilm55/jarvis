"""Tests for jarvis.brain.dispatch."""

import asyncio
from typing import NamedTuple

import pytest

from jarvis.brain.clock import TurnClock
from jarvis.brain.dispatch import TurnHooks, TurnTools
from jarvis.brain.failures import ToolError
from jarvis.contract import FinalResponse
from jarvis.desktop.client import DesktopError


class FakeDesktop:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def open_app(self, query: str) -> dict[str, object]:
        self.calls.append(("open_app", query))
        return {"app": query}

    async def close_app(self, query: str) -> dict[str, object]:
        self.calls.append(("close_app", query))
        return {"ok": True}

    async def volume_get(self) -> dict[str, object]:
        self.calls.append(("volume_get", ""))
        return {"ok": True}

    async def volume_set(self, pct: int) -> dict[str, object]:
        self.calls.append(("volume_set", str(pct)))
        return {"ok": True}

    async def volume_step(self, delta: int) -> dict[str, object]:
        self.calls.append(("volume_step", str(delta)))
        return {"ok": True}

    async def mute(self, on: bool) -> dict[str, object]:
        self.calls.append(("mute", str(on)))
        return {"ok": True}


class Recorder:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.said: list[str] = []
        self.asked: list[tuple[str, list[str]]] = []
        self.finished: list[FinalResponse] = []

    async def on_say(self, text: str) -> None:
        self.said.append(text)

    async def on_ask(self, question: str, options: list[str]) -> str:
        self.events.append("ask")
        self.asked.append((question, options))
        return "yes"

    def finish(self, response: FinalResponse) -> None:
        self.finished.append(response)


class EventClock(TurnClock):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def pause(self) -> None:
        self.events.append("pause")
        super().pause()

    def resume(self) -> None:
        self.events.append("resume")
        super().resume()


class Rig(NamedTuple):
    tools: TurnTools
    rec: Recorder
    desktop: FakeDesktop
    clock: EventClock


def make(max_steps: int = 25) -> Rig:
    events: list[str] = []
    rec = Recorder(events)
    clock = EventClock(events)
    hooks = TurnHooks(on_say=rec.on_say, on_ask=rec.on_ask, finish=rec.finish, clock=clock)
    desktop = FakeDesktop()
    tools = TurnTools("t1", hooks, desktop, max_steps)
    return Rig(tools, rec, desktop, clock)


VALID: dict[str, object] = {"status": "success", "spoken": "Done."}


def run(tools: TurnTools, name: str, args: dict[str, object]) -> object:
    return asyncio.run(tools(name, args))


def test_should_route_say_to_on_say_when_text_provided() -> None:
    rig = make()
    result = run(rig.tools, "jarvis.say", {"text": "hello"})
    assert result == "ok"
    assert rig.rec.said == ["hello"]


def test_should_sanitize_markdown_in_say_when_markup_present() -> None:
    rig = make()
    run(rig.tools, "jarvis.say", {"text": "**Hi** there"})
    assert rig.rec.said == ["Hi there"]


@pytest.mark.parametrize("text", ["", "   ", 5, None])
def test_should_raise_tool_error_when_say_text_invalid(text: object) -> None:
    rig = make()
    with pytest.raises(ToolError):
        run(rig.tools, "jarvis.say", {"text": text})
    assert rig.rec.said == []


def test_should_route_ask_to_on_ask_when_question_provided() -> None:
    rig = make()
    result = run(rig.tools, "jarvis.ask", {"question": "ok?", "options": ["yes", "no"]})
    assert result == "yes"
    assert rig.rec.asked == [("ok?", ["yes", "no"])]


def test_should_use_empty_options_when_ask_options_missing() -> None:
    rig = make()
    result = run(rig.tools, "jarvis.ask", {"question": "ok?"})
    assert result == "yes"
    assert rig.rec.asked == [("ok?", [])]


def test_should_pause_and_resume_clock_around_ask() -> None:
    rig = make()
    run(rig.tools, "jarvis.ask", {"question": "ok?", "options": ["yes"]})
    assert rig.rec.events == ["pause", "ask", "resume"]


def test_should_resume_clock_when_on_ask_raises() -> None:
    class Boom(Recorder):
        async def on_ask(self, question: str, options: list[str]) -> str:
            self.events.append("ask")
            raise RuntimeError("boom")

    events: list[str] = []
    rec = Boom(events)
    clock = EventClock(events)
    hooks = TurnHooks(on_say=rec.on_say, on_ask=rec.on_ask, finish=rec.finish, clock=clock)
    tools = TurnTools("t1", hooks, FakeDesktop(), 25)

    with pytest.raises(RuntimeError):
        asyncio.run(tools("jarvis.ask", {"question": "q", "options": ["yes"]}))
    assert events[-1] == "resume"


@pytest.mark.parametrize("options", ["yes", [1], ["a"] * 11])
def test_should_raise_tool_error_when_ask_options_invalid(options: object) -> None:
    rig = make()
    with pytest.raises(ToolError):
        run(rig.tools, "jarvis.ask", {"question": "q", "options": options})


def test_should_route_respond_to_the_gate_when_policy_is_jarvis_respond() -> None:
    rig = make()
    assert run(rig.tools, "jarvis.respond", VALID) == "ok"
    assert rig.tools.final == rig.rec.finished[0]
    with pytest.raises(ToolError, match="already"):
        run(rig.tools, "jarvis.say", {"text": "late"})


def test_should_raise_when_tools_closed() -> None:
    rig = make()
    rig.tools.close()
    with pytest.raises(ToolError, match="no active turn"):
        run(rig.tools, "jarvis.say", {"text": "hi"})


def test_should_raise_when_policy_unknown() -> None:
    rig = make()
    with pytest.raises(ToolError, match="unknown tool"):
        run(rig.tools, "jarvis.nope", {})


def test_should_route_desktop_open_app_when_name_provided() -> None:
    rig = make()
    result = run(rig.tools, "desktop.open_app", {"name": "Calculator"})
    assert result == {"app": "Calculator"}
    assert rig.desktop.calls == [("open_app", "Calculator")]


def test_should_wrap_desktop_error_when_open_app_fails() -> None:
    class FailingDesktop(FakeDesktop):
        async def open_app(self, query: str) -> dict[str, object]:
            raise DesktopError("NOT_FOUND", "no such app")

    events: list[str] = []
    rec = Recorder(events)
    clock = EventClock(events)
    hooks = TurnHooks(on_say=rec.on_say, on_ask=rec.on_ask, finish=rec.finish, clock=clock)
    tools = TurnTools("t1", hooks, FailingDesktop(), 25)

    with pytest.raises(ToolError, match="NOT_FOUND"):
        asyncio.run(tools("desktop.open_app", {"name": "X"}))


def test_should_count_steps_for_tools_but_not_respond() -> None:
    rig = make()
    run(rig.tools, "jarvis.say", {"text": "hi"})
    run(rig.tools, "jarvis.ask", {"question": "q", "options": ["yes"]})
    run(rig.tools, "desktop.open_app", {"name": "X"})
    assert rig.tools.steps == 3
    run(rig.tools, "jarvis.respond", VALID)
    assert rig.tools.steps == 3


def test_should_raise_when_step_limit_reached() -> None:
    rig = make(max_steps=2)
    run(rig.tools, "jarvis.say", {"text": "a"})
    run(rig.tools, "jarvis.say", {"text": "b"})
    with pytest.raises(ToolError, match="respond now"):
        run(rig.tools, "jarvis.say", {"text": "c"})
    assert rig.desktop.calls == []
    result = run(rig.tools, "jarvis.respond", VALID)
    assert result == "ok"


def test_should_partial_when_hard_step_cap_exceeded() -> None:
    rig = make(max_steps=1)
    run(rig.tools, "jarvis.say", {"text": "a"})
    for i in range(2, 5):
        with pytest.raises(ToolError, match="respond now"):
            run(rig.tools, "jarvis.say", {"text": f"s{i}"})
    with pytest.raises(ToolError, match="step limit exceeded"):
        run(rig.tools, "jarvis.say", {"text": "s5"})
    assert len(rig.rec.finished) == 1
    assert rig.rec.finished[0].status == "partial"
