"""Doubles for the Segmenter tests: scripted endpointer, scorer, deaf flags and clock."""

from typing import cast

import numpy as np

from jarvis.audio import FRAME_SAMPLES, Endpointer, SpeechStart, Utterance
from jarvis.audio.sources import Pcm
from jarvis.orchestrator.segmenter import Segment, Segmenter

FRAME = np.zeros(FRAME_SAMPLES, dtype=np.int16)


def utt() -> Utterance:
    return Utterance(np.zeros(FRAME_SAMPLES, dtype=np.int16), 0.0, 1.0)


class FakeEndpointer:
    def __init__(
        self,
        script: list[list[SpeechStart | Utterance]],
        flushed: list[SpeechStart | Utterance] | None = None,
    ) -> None:
        self.script = script
        self.flushed = flushed
        self.frames: list[Pcm] = []

    def feed(self, frame: Pcm) -> list[SpeechStart | Utterance]:
        self.frames.append(frame)
        if len(self.frames) <= len(self.script):
            return self.script[len(self.frames) - 1]
        return []

    def flush(self) -> list[SpeechStart | Utterance]:
        return self.flushed or []


class FakeScorer:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[Pcm] = []

    def score(self, frame: Pcm) -> float:
        self.calls.append(frame)
        if len(self.calls) <= len(self.scores):
            return self.scores[len(self.calls) - 1]
        return 0.0


class FakeDeaf:
    def __init__(self, flags: list[bool]) -> None:
        self.flags = flags
        self.index = 0

    def __call__(self) -> bool:
        if self.index < len(self.flags):
            flag = self.flags[self.index]
            self.index += 1
            return flag
        return False


def make(
    script: list[list[SpeechStart | Utterance]],
    scores: list[float],
    deaf: list[bool],
    flushed: list[SpeechStart | Utterance] | None = None,
) -> tuple[Segmenter, FakeEndpointer, FakeScorer]:
    endpointer = FakeEndpointer(script, flushed)
    scorer = FakeScorer(scores)
    is_deaf = FakeDeaf(deaf)
    segmenter = Segmenter(cast(Endpointer, endpointer), scorer, is_deaf)
    return segmenter, endpointer, scorer


def run(segmenter: Segmenter, n: int) -> list[Segment]:
    segments: list[Segment] = []
    for _ in range(n):
        segments.extend(segmenter.feed(FRAME))
    return segments
