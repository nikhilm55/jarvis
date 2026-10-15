"""Follow-up window (R60): a final with follow_up_expected opens the reply window."""

import asyncio
from pathlib import Path

from jarvis.contract import FinalResponse
from jarvis.orchestrator.timing import Timing
from tests.core_rig import CoreRig
from tests.listener_rig import seg
from tests.orchestrator_rig import FakeBrain, command, make_rig, until

ASK = FinalResponse(status="needs_input", spoken="Which one?", follow_up_expected=True)
DONE = FinalResponse(status="success", spoken="Opening the second one.")


def test_should_run_the_answer_as_a_new_turn_with_the_pending_question(tmp_path: Path) -> None:
    async def scenario() -> tuple[FakeBrain, list[str]]:
        brain = FakeBrain(finals=[ASK, DONE])
        rig = make_rig(tmp_path, brain)
        task = asyncio.create_task(rig.runner.run(command("open it", None)))
        try:
            await until(lambda: rig.windows.kind == "reply")
            assert rig.windows.offer_answer("the second one") is True
            await asyncio.wait_for(task, 5)
        finally:
            task.cancel()
        return brain, rig.speaker.said

    brain, said = asyncio.run(scenario())

    assert said == ["Which one?", "Opening the second one."]
    first, second = brain.envelopes
    assert first.context.pending_question is None
    assert (second.command, second.raw_transcript) == ("the second one", "the second one")
    assert second.context.pending_question == "Which one?"


def test_should_run_a_spoken_timeout_as_a_new_turn_when_it_answers_the_follow_up(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        brain = FakeBrain(finals=[ASK, DONE])
        rig = make_rig(tmp_path, brain)
        task = asyncio.create_task(rig.runner.run(command("open it", None)))
        try:
            await until(lambda: rig.windows.kind == "reply")
            assert rig.windows.offer_answer("timeout") is True
            await asyncio.wait_for(task, 5)
        finally:
            task.cancel()
        assert [e.command for e in brain.envelopes] == ["open it", "timeout"]

    asyncio.run(scenario())


def test_should_go_idle_when_nobody_answers_the_follow_up(tmp_path: Path) -> None:
    brain = FakeBrain(finals=[ASK])
    rig = make_rig(tmp_path, brain, Timing(reply_window_s=0.02, deaf_tail_s=0.0))

    asyncio.run(asyncio.wait_for(rig.runner.run(command("open it", None)), 5))

    assert len(brain.envelopes) == 1
    assert rig.states[-3:] == ["idle", "listening", "idle"]
    assert len(rig.records()) == 1


def test_should_not_open_a_window_when_no_follow_up_is_expected(tmp_path: Path) -> None:
    brain = FakeBrain(finals=[DONE])
    rig = make_rig(tmp_path, brain)

    asyncio.run(asyncio.wait_for(rig.runner.run(command("open it", None)), 5))

    assert rig.windows.kind is None
    assert "listening" not in rig.states


def test_should_stop_instead_of_answering_when_stop_is_said_in_the_follow_up_window(
    tmp_path: Path,
) -> None:
    async def scenario() -> CoreRig:
        rig = CoreRig(tmp_path, ["Jarvis, open it", "Jarvis, stop"], finals=[ASK, DONE])
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await until(lambda: "listening" in rig.states)
            rig.feed.push(seg())
            await until(lambda: rig.speaker.earcons == ["done"])
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        return rig

    rig = asyncio.run(scenario())

    assert rig.brain is not None
    assert len(rig.brain.envelopes) == 1
    assert rig.speaker.said == ["Which one?"]
