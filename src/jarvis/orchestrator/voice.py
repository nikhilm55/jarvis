"""Speaking for the voice loop: tracks what Jarvis says so the wake stage can stay deaf (R47)."""

import asyncio
import threading
import time
from collections.abc import Callable

from jarvis.log import get_logger
from jarvis.orchestrator.ports import SpeakerPort
from jarvis.orchestrator.timing import Timing
from jarvis.tts import SpeechHandle

__all__ = ["Voice"]


class Voice:
    """Tracks active speech so the wake stage can stay deaf while Jarvis talks."""

    def __init__(
        self,
        speaker: SpeakerPort,
        timing: Timing,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a Voice bound to a speaker, timing profile and monotonic clock."""
        self._speaker = speaker
        self._timing = timing
        self._clock = clock
        self._lock = threading.Lock()
        self._live: tuple[SpeechHandle, ...] = ()
        self._deaf_until: float = 0.0

    def say(self, text: str) -> SpeechHandle:
        """Speak text and return a handle to the utterance."""
        return self._started(lambda: self._speaker.say(text), "say")

    def earcon(self, name: str) -> SpeechHandle:
        """Play a named earcon and return a handle to the utterance."""
        return self._started(lambda: self._speaker.earcon(name), "earcon")

    def is_deaf(self) -> bool:
        """Return True while Jarvis is speaking or inside the deaf tail."""
        live = self._live
        if any(h.is_speaking for h in live):
            self._deaf_until = self._clock() + self._timing.deaf_tail_s
            return True
        return self._clock() < self._deaf_until

    async def wait(self, handle: SpeechHandle) -> None:
        """Wait for a handle to finish and then observe the deaf tail."""
        while handle.is_speaking:
            await asyncio.to_thread(handle.wait, 0.5)
        tail = self._timing.deaf_tail_s
        self._deaf_until = self._clock() + tail
        await asyncio.sleep(tail)

    def cancel_all(self) -> None:
        """Cancel every live handle and clear the live set."""
        with self._lock:
            handles = self._live
            self._live = ()
        for handle in handles:
            handle.cancel()

    def _started(self, start: Callable[[], SpeechHandle], label: str) -> SpeechHandle:
        """Start a handle, falling back to a dead handle if the speaker is closed."""
        try:
            handle = start()
        except RuntimeError:
            get_logger("voice").warning("speaker unavailable")
            dead = SpeechHandle(label, self._clock)
            dead.cancel()
            return dead
        self._track(handle)
        return handle

    def _track(self, handle: SpeechHandle) -> None:
        """Record a handle as live, dropping any that have already ended."""
        with self._lock:
            self._live = (*(h for h in self._live if h.is_speaking), handle)
