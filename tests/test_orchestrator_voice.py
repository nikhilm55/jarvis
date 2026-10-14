"""Tests for jarvis.orchestrator.voice."""

import asyncio

from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.voice import Voice
from jarvis.tts import SpeechHandle


class FakeClock:
    """A controllable clock returning a mutable now value."""

    def __init__(self) -> None:
        self.now: float = 0.0

    def __call__(self) -> float:
        return self.now


class FakeSpeaker:
    """A speaker double that records calls and can simulate failure."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.said: list[str] = []
        self.earcons: list[str] = []
        self.handles: list[SpeechHandle] = []
        self.fail: bool = False

    def say(self, text: str) -> SpeechHandle:
        if self.fail:
            raise RuntimeError("speaker is closed")
        handle = SpeechHandle(text, self.clock)
        self.said.append(text)
        self.handles.append(handle)
        return handle

    def earcon(self, name: str) -> SpeechHandle:
        if self.fail:
            raise RuntimeError("speaker is closed")
        handle = SpeechHandle(name, self.clock)
        self.earcons.append(name)
        self.handles.append(handle)
        return handle

    def close(self) -> None:
        pass


def make(deaf_tail_s: float = 0.3) -> tuple[Voice, FakeSpeaker, FakeClock]:
    clock = FakeClock()
    speaker = FakeSpeaker(clock)
    voice = Voice(speaker, Timing(deaf_tail_s=deaf_tail_s), clock=clock)
    return voice, speaker, clock


def test_should_forward_to_speaker_and_return_handle_when_saying() -> None:
    voice, speaker, _ = make()
    handle = voice.say("hello")
    assert speaker.said == ["hello"]
    assert handle is speaker.handles[0]


def test_should_forward_to_speaker_and_return_handle_when_earconning() -> None:
    voice, speaker, _ = make()
    handle = voice.earcon("ding")
    assert speaker.earcons == ["ding"]
    assert handle is speaker.handles[0]


def test_should_not_be_deaf_when_fresh() -> None:
    voice, _, _ = make()
    assert voice.is_deaf() is False


def test_should_be_deaf_while_say_handle_is_speaking() -> None:
    voice, _, clock = make()
    handle = voice.say("hi")
    assert voice.is_deaf() is True
    handle.cancel()
    clock.now = 10.0
    assert voice.is_deaf() is False


def test_should_be_deaf_for_tail_after_handle_ended_then_not() -> None:
    voice, _, clock = make()
    clock.now = 0.0
    handle = voice.say("hi")
    assert voice.is_deaf() is True
    handle.cancel()
    clock.now = 0.2
    assert voice.is_deaf() is True
    clock.now = 0.31
    assert voice.is_deaf() is False


def test_should_be_deaf_while_earcon_handle_is_speaking() -> None:
    voice, _, clock = make()
    handle = voice.earcon("ding")
    assert voice.is_deaf() is True
    handle.cancel()
    clock.now = 10.0
    assert voice.is_deaf() is False


def test_should_be_deaf_right_after_wait_returns() -> None:
    voice, _, _ = make(deaf_tail_s=0.01)
    handle = voice.say("hi")

    async def scenario() -> None:
        task = asyncio.create_task(voice.wait(handle))
        await asyncio.sleep(0)
        handle.cancel()
        await task

    asyncio.run(scenario())
    assert voice.is_deaf() is True


def test_should_not_block_event_loop_while_waiting() -> None:
    voice, _, _ = make(deaf_tail_s=0.01)
    handle = voice.say("hi")
    counter = 0

    async def scenario() -> None:
        nonlocal counter
        task = asyncio.create_task(voice.wait(handle))
        for _ in range(3):
            await asyncio.sleep(0)
            counter += 1
        handle.cancel()
        await task

    asyncio.run(scenario())
    assert counter == 3


def test_should_cancel_all_tracked_handles_and_stop_being_deaf() -> None:
    voice, _, clock = make()
    h1 = voice.say("one")
    h2 = voice.say("two")
    voice.cancel_all()
    assert h1.cancelled is True
    assert h2.cancelled is True
    clock.now = 10.0
    assert voice.is_deaf() is False


def test_should_return_cancelled_handle_when_speaker_raises_on_say() -> None:
    voice, speaker, _ = make()
    speaker.fail = True
    handle = voice.say("hi")
    assert handle.is_speaking is False
    assert handle.cancelled is True


def test_should_return_cancelled_handle_when_speaker_raises_on_earcon() -> None:
    voice, speaker, _ = make()
    speaker.fail = True
    handle = voice.earcon("ding")
    assert handle.is_speaking is False
    assert handle.cancelled is True
