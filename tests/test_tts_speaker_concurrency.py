"""Tests pinning that Speaker never runs two engine.synthesize() calls at once."""

import threading

import numpy as np
import numpy.typing as npt

from jarvis.tts.speaker import Speaker
from tests.tts_fakes import FakeSink


class CountingEngine:
    """Engine that tracks concurrent synthesize calls and gates the first one."""

    def __init__(self) -> None:
        self.sample_rate = 24000
        self._lock = threading.Lock()
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.texts: list[str] = []
        self.first_entered = threading.Event()
        self.later_entered = threading.Event()
        self.release = threading.Event()

    def synthesize(self, text: str) -> npt.NDArray[np.float32]:
        with self._lock:
            self.calls += 1
            index = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.texts.append(text)
            if index == 1:
                self.first_entered.set()
            else:
                self.later_entered.set()
        if index == 1:
            self.release.wait(timeout=5.0)
        audio = np.full(2400, 0.1, dtype=np.float32)
        with self._lock:
            self.active -= 1
        return audio


def test_should_not_start_second_synthesis_while_cancelled_one_is_still_running() -> None:
    engine = CountingEngine()
    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=FakeSink,
    )
    try:
        h1 = speaker.say("One.")
        assert engine.first_entered.wait(5.0)
        h1.cancel()
        h2 = speaker.say("Two.")
        assert not engine.later_entered.wait(0.3)
        engine.release.set()
        assert h2.wait(5.0)
        assert engine.max_active == 1
        assert engine.texts == ["One.", "Two."]
    finally:
        speaker.close()


def test_should_not_stall_the_worker_after_cancel_when_synthesis_is_slow() -> None:
    engine = CountingEngine()
    speaker = Speaker(
        engine_factory=lambda: engine,
        sink_factory=FakeSink,
    )
    try:
        h1 = speaker.say("One.")
        assert engine.first_entered.wait(5.0)
        h1.cancel()
        assert h1.wait(0)
        h2 = speaker.say("Two.")
        engine.release.set()
        assert h2.wait(5.0)
        assert h2.first_audio_s is not None
        assert engine.max_active == 1
    finally:
        speaker.close()
