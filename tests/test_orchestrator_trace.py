"""Tests for jarvis.orchestrator.trace."""

import asyncio

import pytest

from jarvis.activity import ToolCallRecord
from jarvis.orchestrator.trace import ToolTrace


def test_should_return_inner_result_and_record_call_when_wrapped_dispatch_is_called() -> None:
    async def scenario() -> None:
        trace = ToolTrace()
        calls: list[tuple[str, dict[str, object]]] = []

        async def inner(name: str, args: dict[str, object]) -> object:
            calls.append((name, dict(args)))
            return "ok"

        wrapped = trace.wrap(inner)
        result = await wrapped("jarvis.say", {"text": "hi"})
        assert result == "ok"
        assert calls == [("jarvis.say", {"text": "hi"})]
        records = trace.take()
        assert records == [ToolCallRecord("jarvis.say", {"text": "hi"})]

    asyncio.run(scenario())


def test_should_record_calls_in_order_and_clear_on_take_when_multiple_calls_are_made() -> None:
    async def scenario() -> None:
        trace = ToolTrace()

        async def inner(name: str, args: dict[str, object]) -> object:
            return name

        wrapped = trace.wrap(inner)
        await wrapped("tool.a", {"x": 1})
        await wrapped("tool.b", {"y": 2})
        first = trace.take()
        assert first == [
            ToolCallRecord("tool.a", {"x": 1}),
            ToolCallRecord("tool.b", {"y": 2}),
        ]
        second = trace.take()
        assert second == []

    asyncio.run(scenario())


def test_should_record_call_and_propagate_error_when_inner_raises() -> None:
    async def scenario() -> None:
        trace = ToolTrace()

        async def inner(name: str, args: dict[str, object]) -> object:
            raise RuntimeError("boom")

        wrapped = trace.wrap(inner)
        with pytest.raises(RuntimeError, match="boom"):
            await wrapped("tool.fail", {"z": 3})
        records = trace.take()
        assert records == [ToolCallRecord("tool.fail", {"z": 3})]

    asyncio.run(scenario())


def test_should_store_copy_of_args_when_caller_mutates_dict_after_call() -> None:
    async def scenario() -> None:
        trace = ToolTrace()

        async def inner(name: str, args: dict[str, object]) -> object:
            return None

        wrapped = trace.wrap(inner)
        args: dict[str, object] = {"text": "hi"}
        await wrapped("jarvis.say", args)
        args["text"] = "changed"
        records = trace.take()
        assert records == [ToolCallRecord("jarvis.say", {"text": "hi"})]

    asyncio.run(scenario())


def test_should_keep_only_first_200_calls_when_more_than_200_are_recorded() -> None:
    async def scenario() -> None:
        trace = ToolTrace()

        async def inner(name: str, args: dict[str, object]) -> object:
            return None

        wrapped = trace.wrap(inner)
        for i in range(250):
            await wrapped(f"tool.{i}", {"i": i})
        records = trace.take()
        assert len(records) == 200
        assert records[0] == ToolCallRecord("tool.0", {"i": 0})
        assert records[-1] == ToolCallRecord("tool.199", {"i": 199})

    asyncio.run(scenario())
