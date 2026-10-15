"""Tests for how the TurnRunner drives the brain: envelope, on_say, on_ask, tool calls."""

import asyncio
from pathlib import Path

from jarvis.brain.dispatch import OnAsk, OnSay
from jarvis.contract import FinalResponse
from jarvis.orchestrator.timing import Timing
from tests.orchestrator_rig import FakeBrain, command, make_rig, until


def test_should_carry_the_turn_facts_in_the_envelope_when_the_brain_turns(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        brain = FakeBrain(final=FinalResponse(status="success", spoken="Done."))
        rig = make_rig(tmp_path, brain=brain)
        task = asyncio.create_task(rig.runner.run(command("open the app", None)))
        try:
            await task
        finally:
            task.cancel()
        envelope = brain.envelopes[0]
        assert envelope.command == "open the app"
        assert envelope.raw_transcript == "Jarvis, open the app"
        assert envelope.stt.engine == "whisper.cpp/tiny.en"
        assert envelope.input_mode == "voice"
        assert envelope.policy.mode == "balanced"
        assert envelope.policy.max_steps == 25

    asyncio.run(scenario())


def test_should_speak_and_show_text_when_on_say_is_called(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            await on_say("Working on it.")
            return FinalResponse(status="success", spoken="Done.")

        brain = FakeBrain(script=script)
        rig = make_rig(tmp_path, brain=brain)
        task = asyncio.create_task(rig.runner.run(command("do something", None)))
        try:
            await task
        finally:
            task.cancel()
        assert rig.speaker.said == ["Working on it.", "Done."]
        speaking = [e for e in rig.hud_events if e.state == "speaking"]
        assert any(e.text == "Working on it." for e in speaking)

    asyncio.run(scenario())


def test_should_cancel_thinking_earcon_when_on_say_fires(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            await on_say("One moment.")
            await asyncio.sleep(0.2)
            return FinalResponse(status="success", spoken="Done.")

        timing = Timing(thinking_after_s=0.05, deaf_tail_s=0.0)
        brain = FakeBrain(script=script)
        rig = make_rig(tmp_path, brain=brain, timing=timing)
        task = asyncio.create_task(rig.runner.run(command("think", None)))
        try:
            await task
        finally:
            task.cancel()
        assert rig.speaker.earcons == []

    asyncio.run(scenario())


def test_should_return_user_answer_when_on_ask_is_answered(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            answer = await on_ask("Which one?", ["first", "second"])
            return FinalResponse(status="success", spoken=f"You picked {answer}.")

        brain = FakeBrain(script=script)
        rig = make_rig(tmp_path, brain=brain)
        task = asyncio.create_task(rig.runner.run(command("pick", None)))
        try:
            await until(lambda: rig.windows.kind == "reply")
            assert rig.windows.offer_answer("the second one") is True
            await task
        finally:
            task.cancel()
        assert rig.speaker.said == ["Which one?", "You picked the second one."]
        assert "listening" in rig.states
        reply_events = [e for e in rig.hud_events if e.state == "reply"]
        assert any(
            e.text == "Which one?" and e.extra == {"options": ["first", "second"]}
            for e in reply_events
        )

    asyncio.run(scenario())


def test_should_tell_the_brain_nobody_replied_when_on_ask_expires(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            answer = await on_ask("Which one?", ["first", "second"])
            return FinalResponse(status="success", spoken=f"Got {answer}.")

        timing = Timing(reply_window_s=0.02, deaf_tail_s=0.0)
        brain = FakeBrain(script=script)
        rig = make_rig(tmp_path, brain=brain, timing=timing)
        task = asyncio.create_task(rig.runner.run(command("pick", None)))
        try:
            await task
        finally:
            task.cancel()
        assert rig.speaker.said[-1] == "Got (no reply from the user within 0.02 seconds)."

    asyncio.run(scenario())


def test_should_note_brain_turn_in_activity_record_when_turn_succeeds(tmp_path: Path) -> None:
    async def scenario() -> None:
        brain = FakeBrain(final=FinalResponse(status="success", spoken="Done."))
        rig = make_rig(tmp_path, brain=brain)
        task = asyncio.create_task(rig.runner.run(command("do it", None)))
        try:
            await task
        finally:
            task.cancel()
        record = rig.records()[0]
        assert record["brain_model"] == "sonnet"
        assert record["route"] == "brain"
        assert "brain" in record["durations_ms"]

    asyncio.run(scenario())


def test_should_record_tool_calls_from_trace_when_brain_uses_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def inner(name: str, args: dict[str, object]) -> object:
            return "ok"

        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            await rig.trace.wrap(inner)("desktop.open_app", {"query": "calculator"})
            return FinalResponse(status="success", spoken="Done.")

        brain = FakeBrain(script=script)
        rig = make_rig(tmp_path, brain=brain)
        task = asyncio.create_task(rig.runner.run(command("open app", None)))
        try:
            await task
        finally:
            task.cancel()
        record = rig.records()[0]
        assert record["tool_calls"] == [
            {"tool": "desktop.open_app", "args": {"query": "calculator"}}
        ]

    asyncio.run(scenario())


def test_should_pass_a_spoken_timeout_to_the_brain_as_the_users_answer(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            answer = await on_ask("Which mode?", [])
            return FinalResponse(status="success", spoken=f"Got {answer}.")

        rig = make_rig(tmp_path, brain=FakeBrain(script=script))
        task = asyncio.create_task(rig.runner.run(command("pick", None)))
        try:
            await until(lambda: rig.windows.kind == "reply")
            assert rig.windows.offer_answer("timeout") is True
            await task
        finally:
            task.cancel()
        assert rig.speaker.said[-1] == "Got timeout."

    asyncio.run(scenario())
