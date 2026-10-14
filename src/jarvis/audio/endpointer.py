"""Turns frames into `SpeechStart` / `Utterance` events with a VAD (FR-ACT-02/03/05)."""

from dataclasses import dataclass

import numpy as np

from jarvis.audio.preroll import PreRoll
from jarvis.audio.sources import SAMPLE_RATE, Pcm
from jarvis.audio.vad import WINDOW_SAMPLES, Vad

START_THRESHOLD = 0.5  # speech probability that begins an utterance
CONTINUE_THRESHOLD = 0.35  # probability that keeps one going (hysteresis)


@dataclass(frozen=True)
class SpeechStart:
    silence_before_ms: int  # continuous non-speech just before this speech (FR-ACT-05 needs 400)


@dataclass(frozen=True)
class Utterance:
    """`pcm` is the pre-roll plus the speech and trailing silence; times are seconds of audio fed
    so far, and cover exactly `pcm` (so `started_at` is where the pre-roll begins)."""

    pcm: Pcm
    started_at: float
    ended_at: float


Event = SpeechStart | Utterance


class Endpointer:
    def __init__(self, vad: Vad, trailing_ms: int = 700, cap_s: int = 30) -> None:
        self._vad = vad
        self._trailing = trailing_ms * SAMPLE_RATE // 1000
        self._cap = cap_s * SAMPLE_RATE
        self._preroll = PreRoll()
        self._pending: Pcm = np.zeros(0, dtype=np.int16)
        self._consumed = 0  # samples already through the VAD
        self._quiet = 0  # consecutive non-speech samples (the stream start counts as quiet)
        self._speaking = False
        self._speech: list[Pcm] = []  # the open utterance's audio
        self._speech_len = 0
        self._silent = 0  # trailing non-speech samples inside the open utterance
        self._begun = 0  # stream position of the open utterance's first sample

    def feed(self, frame: Pcm) -> list[Event]:
        if frame.ndim != 1 or frame.dtype != np.int16:
            raise ValueError(f"expected a 1-D int16 frame, got {frame.dtype} {frame.shape}")
        self._pending = np.concatenate([self._pending, frame])
        events: list[Event] = []
        while len(self._pending) >= WINDOW_SAMPLES:
            window, self._pending = self._pending[:WINDOW_SAMPLES], self._pending[WINDOW_SAMPLES:]
            events.extend(self._window(window))
        return events

    def flush(self) -> list[Event]:
        """End of stream: close the open utterance, if any, as if it had ended here."""
        return [self._finish()] if self._speaking else []

    def _window(self, window: Pcm) -> list[Event]:
        probability = self._vad.prob(window)
        self._consumed += len(window)
        if not self._speaking:
            if probability < START_THRESHOLD:
                self._quiet += len(window)
                self._preroll.push(window)
                return []
            lead = self._preroll.snapshot()
            event = SpeechStart(silence_before_ms=self._quiet * 1000 // SAMPLE_RATE)
            self._begun = self._consumed - len(window) - len(lead)
            self._speaking, self._speech = True, [lead]
            self._speech_len, self._silent, self._quiet = len(lead), 0, 0
            self._append(window)
            return [event, *self._closed()]
        if probability >= CONTINUE_THRESHOLD:
            self._silent = 0
        else:
            self._silent += len(window)
        self._append(window)
        return self._closed()

    def _append(self, window: Pcm) -> None:
        room = self._cap - self._speech_len
        self._speech.append(window[:room])
        self._speech_len += min(len(window), room)

    def _closed(self) -> list[Event]:
        if self._silent >= self._trailing or self._speech_len >= self._cap:
            return [self._finish()]
        return []

    def _finish(self) -> Utterance:
        pcm = np.concatenate(self._speech)
        started = self._begun / SAMPLE_RATE
        utterance = Utterance(pcm, started, started + len(pcm) / SAMPLE_RATE)
        self._quiet = self._silent  # the trailing silence is still silence before the next speech
        self._speaking = False
        self._preroll.clear()
        self._vad.reset()
        return utterance
