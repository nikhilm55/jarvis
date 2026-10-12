"""Tests for cancelling in-flight say/ask callbacks when a turn closes."""

import asyncio
import contextlib
from typing import Any, cast

import pytest

from jarvis.brain.clock import TurnClock
from jarvis.brain.desktop_tools import DesktopLike
from jarvis.brain.dispatch import TurnHooks, TurnTools
from jarvis.brain.failures import ToolError


class Blocking:
    """A turn callback pair that blocks until cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def on_say(self, text: str) -> None:
        """Block on a say callback until cancelled."""
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def on_ask(self, question: str, options: list[str]) -> str:
        """Block on an ask callback until cancelled."""
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return options[0]


def _make_tools(blocking: Blocking, clock: TurnClock | None = None) -> TurnTools:
    """Build TurnTools wired to the blocking callbacks."""
    hooks = TurnHooks(
        on_say=blocking.on_say,
        on_ask=blocking.on_ask,
        finish=lambda response: None,
        clock=clock if clock is not None else TurnClock(),
    )
    return TurnTools(
        turn_id="turn-1",
        hooks=hooks,
        desktop=cast(DesktopLike, None),
        max_steps=3,
    )


def test_should_cancel_an_inflight_ask_when_the_turn_closes() -> None:
    """Closing the turn cancels an in-flight ask callback."""

    async def scenario() -> None:
        blocking = Blocking()
        tools = _make_tools(blocking)
        task = asyncio.create_task(tools("jarvis.ask", {"question": "Which one?"}))
        try:
            await asyncio.wait_for(blocking.started.wait(), 10)
            tools.close()
            with pytest.raises(ToolError, match="turn ended"):
                await asyncio.wait_for(task, 5)
            assert blocking.cancelled is True
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ToolError):
                    await task

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_should_cancel_an_inflight_say_when_the_turn_closes() -> None:
    """Closing the turn cancels an in-flight say callback."""

    async def scenario() -> None:
        blocking = Blocking()
        tools = _make_tools(blocking)
        task = asyncio.create_task(tools("jarvis.say", {"text": "Working on it."}))
        try:
            await asyncio.wait_for(blocking.started.wait(), 10)
            tools.close()
            with pytest.raises(ToolError, match="turn ended"):
                await asyncio.wait_for(task, 5)
            assert blocking.cancelled is True
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ToolError):
                    await task

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_should_resume_the_clock_without_error_when_the_turn_scope_already_exited() -> None:
    """Resuming the clock after the timeout scope exits does not raise."""

    async def scenario() -> None:
        clock = TurnClock()
        blocking = Blocking()
        tools = _make_tools(blocking, clock)
        task: asyncio.Task[Any] | None = None
        try:
            async with asyncio.timeout(30) as scope:
                clock.attach(scope)
                task = asyncio.create_task(tools("jarvis.ask", {"question": "Which one?"}))
                await asyncio.wait_for(blocking.started.wait(), 10)
            # scope exits here while the ask is still blocked
            tools.close()
            with pytest.raises(ToolError, match="turn ended"):
                await asyncio.wait_for(task, 5)
            assert blocking.cancelled is True
        finally:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ToolError):
                    await task

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_should_leave_the_caller_cancellable_when_close_is_not_the_cause() -> None:
    """A caller-initiated cancel still surfaces CancelledError."""

    async def scenario() -> None:
        blocking = Blocking()
        tools = _make_tools(blocking)
        task = asyncio.create_task(tools("jarvis.ask", {"question": "Which one?"}))
        try:
            await asyncio.wait_for(blocking.started.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert blocking.cancelled is True
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ToolError):
                    await task

    asyncio.run(asyncio.wait_for(scenario(), 10))
