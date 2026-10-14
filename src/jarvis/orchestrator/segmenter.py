"""Frames in, speech segments out: the endpointer plus the wake detector's peak (FR-ACT-02..05)."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from jarvis.audio import Endpointer, SpeechStart, Utterance
from jarvis.audio.sources import Pcm

__all__ = ["Scorer", "Segment", "SegmentEvent", "Segmenter", "SpeechStarted"]


@dataclass(frozen=True)
class Segment:
    """A closed speech segment with its metadata."""

    utterance: Utterance
    silence_before_ms: int
    wake_score: float
    tainted: bool


@dataclass(frozen=True)
class SpeechStarted:
    """The VAD saw speech begin at this time.clock() value (monotonic seconds)."""

    at: float


SegmentEvent = Segment | SpeechStarted


class Scorer(Protocol):
    """What the wake detector offers to the segmenter."""

    def score(self, frame: Pcm) -> float:
        """Return the wake score for a single frame."""
        ...

    def reset(self) -> None:
        """Forget the audio seen so far (the model's features go stale while it is not fed)."""
        ...


class Segmenter:
    """Turns endpointer events into scored, taint-flagged segments."""

    def __init__(
        self,
        endpointer: Endpointer,
        scorer: Scorer,
        is_deaf: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the endpointer, scorer, deafness probe and clock."""
        self._endpointer = endpointer
        self._scorer = scorer
        self._is_deaf = is_deaf
        self._clock = clock
        self._open = False
        self._silence = 0
        self._peak = 0.0
        self._tainted = False
        self._previous = 0.0
        self._was_deaf = False

    def feed(self, frame: Pcm) -> list[SegmentEvent]:
        """Consume one frame and return any segments or speech-start markers."""
        deaf = self._is_deaf()
        if self._was_deaf and not deaf:
            self._scorer.reset()
            self._previous = 0.0
        self._was_deaf = deaf
        score = 0.0 if deaf else self._scorer.score(frame)
        events = self._endpointer.feed(frame)
        result: list[SegmentEvent] = []
        for event in events:
            if isinstance(event, SpeechStart):
                result.append(SpeechStarted(self._clock()))
                self._open = True
                self._silence = event.silence_before_ms
                self._peak = max(self._previous, score)
                self._tainted = False
            elif isinstance(event, Utterance):
                if self._open:
                    result.append(self._close(event, score, deaf))
                else:
                    result.append(Segment(event, 0, score, deaf))
        if self._open:
            self._peak = max(self._peak, score)
            self._tainted = self._tainted or deaf
        self._previous = score
        return result

    def flush(self) -> list[Segment]:
        """Close the endpointer and return any final segment."""
        events = self._endpointer.flush()
        result: list[Segment] = []
        for event in events:
            if isinstance(event, Utterance) and self._open:
                result.append(self._close(event, 0.0, False))
        return result

    def _close(self, utterance: Utterance, score: float, deaf: bool) -> Segment:
        """Build a Segment from the open state and close it."""
        peak = max(self._peak, score)  # the closing frame counts too
        segment = Segment(utterance, self._silence, peak, self._tainted or deaf)
        self._open = False
        self._silence = 0
        self._peak = 0.0
        self._tainted = False
        return segment
