"""FR-TALK-02: the thinking earcon plays at end of speech + 1.2 s if nothing has been said yet.

Time is a fake clock moved by the test, so each case fixes the moment the reply is ready.
"""

import asyncio
import dataclasses
import time
from pathlib import Path

import pytest

from jarvis.brain.dispatch import OnAsk, OnSay
from jarvis.contract import FinalResponse
from jarvis.orchestrator.timing import Timing
from jarvis.tts import SpeechHandle
from tests.orchestrator_rig import FakeBrain, FakeSpeaker, FakeTimers, command, make_rig

EOS = 100.0
REPLY = "Handled by the brain."


class SerialSpeaker(FakeSpeaker):
    """Like the real Speaker: one job at a time, so an earcon that plays on holds up the reply."""

    def __init__(self) -> None:
        super().__init__()
        self.earcon_handles: list[SpeechHandle] = []
        self.log: list[str] = []  # "earcon:<name>" and "say:<text>" in the order they started
        self.earcon_playing_at_say: list[bool] = []

    def earcon(self, name: str) -> SpeechHandle:
        self.earcons.append(name)
        self.log.append(f"earcon:{name}")
        handle = SpeechHandle(name, time.monotonic)  # open until cancelled
        self.earcon_handles.append(handle)
        return handle

    def say(self, text: str) -> SpeechHandle:
        self.log.append(f"say:{text}")
        self.earcon_playing_at_say.append(any(h.is_speaking for h in self.earcon_handles))
        return super().say(text)


class Scene:
    """One turn with a held brain, a serial speaker and fake time starting at end of speech."""

    def __init__(self, tmp_path: Path, brain: FakeBrain) -> None:
        self.timers = FakeTimers(EOS)
        self.speaker = SerialSpeaker()
        self.brain = brain
        self.rig = make_rig(
            tmp_path,
            brain,
            Timing(deaf_tail_s=0.0),  # thinking_after_s stays the product default
            speaker=self.speaker,
            timers=self.timers,
        )
        self.task: asyncio.Task[None] | None = None

    async def start(self, at: float = EOS) -> None:
        self.timers.now = at  # when the turn begins; slow speech-to-text starts it late
        cmd = dataclasses.replace(command("do something", None), speech_ended_at=EOS)
        self.task = asyncio.create_task(self.rig.runner.run(cmd))
        self.task.add_done_callback(lambda _t: None)
        await self.timers.advance_to(at)  # the turn is running; time has not moved

    async def finish(self) -> None:
        assert self.task is not None
        await asyncio.wait_for(self.task, 2)


def held_brain() -> FakeBrain:
    brain = FakeBrain()
    brain.release = asyncio.Event()
    return brain


def test_should_schedule_the_thinking_earcon_at_end_of_speech_plus_1_2_seconds(
    tmp_path: Path,
) -> None:
    async def scenario() -> list[float]:
        scene = Scene(tmp_path, held_brain())
        await scene.start()
        assert scene.brain.release is not None
        scene.brain.release.set()
        await scene.finish()
        return scene.timers.requested

    assert asyncio.run(scenario()) == [pytest.approx(1.2)]


def test_should_give_no_earcon_when_the_reply_is_ready_before_1_2_seconds(tmp_path: Path) -> None:
    async def scenario() -> Scene:
        scene = Scene(tmp_path, held_brain())
        await scene.start()
        await scene.timers.advance_to(EOS + 1.0)
        assert scene.speaker.earcons == []  # still inside the 1.2 s
        assert scene.brain.release is not None
        scene.brain.release.set()
        await scene.finish()
        await scene.timers.advance_to(EOS + 5.0)  # the timer must have been cancelled
        return scene

    scene = asyncio.run(scenario())

    assert scene.speaker.log == [f"say:{REPLY}"]


def test_should_play_the_earcon_at_1_2_seconds_and_then_the_reply(tmp_path: Path) -> None:
    async def scenario() -> Scene:
        scene = Scene(tmp_path, held_brain())
        await scene.start()
        await scene.timers.advance_to(EOS + 1.19)
        assert scene.speaker.earcons == []
        await scene.timers.advance_to(EOS + 1.2)
        assert scene.speaker.log == ["earcon:thinking"]
        await scene.timers.advance_to(EOS + 1.5)
        assert scene.brain.release is not None
        scene.brain.release.set()
        await scene.finish()
        return scene

    scene = asyncio.run(scenario())

    assert scene.speaker.log == ["earcon:thinking", f"say:{REPLY}"]


def test_should_cut_the_earcon_that_is_still_playing_when_the_reply_is_ready(
    tmp_path: Path,
) -> None:
    async def scenario() -> Scene:
        scene = Scene(tmp_path, held_brain())
        await scene.start()
        await scene.timers.advance_to(EOS + 1.2)
        assert scene.speaker.earcon_handles[0].is_speaking  # the chime is mid-play
        assert scene.brain.release is not None
        scene.brain.release.set()
        await scene.finish()
        return scene

    scene = asyncio.run(scenario())

    assert scene.speaker.earcon_handles[0].cancelled
    assert scene.speaker.earcon_playing_at_say == [False]  # the reply did not queue behind it


def test_should_never_play_the_earcon_after_reply_speech_has_started(tmp_path: Path) -> None:
    async def scenario() -> Scene:
        release = asyncio.Event()

        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            await on_say("Working on it.")  # speech starts at end of speech + 0.5 s
            await release.wait()
            return FinalResponse(status="success", spoken="Done.")

        scene = Scene(tmp_path, FakeBrain(script=script))
        await scene.start()
        await scene.timers.advance_to(EOS + 0.5)
        assert scene.speaker.log == ["say:Working on it."]
        await scene.timers.advance_to(EOS + 2.0)  # past 1.2 s: no earcon over the speech
        release.set()
        await scene.finish()
        return scene

    scene = asyncio.run(scenario())

    assert scene.speaker.earcons == []
    assert scene.speaker.log == ["say:Working on it.", "say:Done."]


def test_should_cut_the_earcon_when_the_brain_asks_a_question(tmp_path: Path) -> None:
    async def scenario() -> Scene:
        release = asyncio.Event()

        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            await release.wait()
            await on_ask("Which one?", ["a", "b"])
            return FinalResponse(status="success", spoken="Done.")

        scene = Scene(tmp_path, FakeBrain(script=script))
        await scene.start()
        await scene.timers.advance_to(EOS + 1.3)
        assert scene.speaker.earcon_handles[0].is_speaking
        release.set()
        await scene.timers.advance_to(EOS + 1.4)
        assert scene.speaker.earcon_handles[0].cancelled
        assert scene.speaker.earcon_playing_at_say == [False]
        assert scene.task is not None
        scene.rig.windows.close()  # end the reply window the question opened
        await scene.finish()
        return scene

    asyncio.run(scenario())


def test_should_play_the_earcon_at_1_2_seconds_even_when_the_turn_starts_late(
    tmp_path: Path,
) -> None:
    async def scenario() -> Scene:
        scene = Scene(tmp_path, held_brain())
        await scene.start(at=EOS + 1.0)  # speech-to-text took 1.0 s
        assert scene.timers.requested == [pytest.approx(0.2)]
        await scene.timers.advance_to(EOS + 1.19)
        assert scene.speaker.earcons == []
        await scene.timers.advance_to(EOS + 1.2)
        assert scene.speaker.log == ["earcon:thinking"]
        assert scene.brain.release is not None
        scene.brain.release.set()
        await scene.finish()
        return scene

    asyncio.run(scenario())


def test_should_play_the_earcon_at_once_when_the_turn_starts_after_1_2_seconds(
    tmp_path: Path,
) -> None:
    async def scenario() -> Scene:
        scene = Scene(tmp_path, held_brain())
        await scene.start(at=EOS + 2.0)
        assert scene.timers.requested == [0.0]
        assert scene.speaker.log == ["earcon:thinking"]
        assert scene.brain.release is not None
        scene.brain.release.set()
        await scene.finish()
        return scene

    asyncio.run(scenario())


def test_should_cut_the_earcon_when_the_brain_speaks_a_progress_line(tmp_path: Path) -> None:
    async def scenario() -> Scene:
        release = asyncio.Event()

        async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
            await release.wait()
            await on_say("Working on it.")
            return FinalResponse(status="success", spoken="Done.")

        scene = Scene(tmp_path, FakeBrain(script=script))
        await scene.start()
        await scene.timers.advance_to(EOS + 1.2)
        assert scene.speaker.earcon_handles[0].is_speaking
        release.set()
        await scene.timers.advance_to(EOS + 1.5)
        assert scene.speaker.earcon_handles[0].cancelled
        assert scene.speaker.earcon_playing_at_say[0] is False
        await scene.finish()
        return scene

    asyncio.run(scenario())
