"""Tests for the Segmenter's speech-start markers and the wake detector reset after deafness."""

from typing import cast

from jarvis.audio import Endpointer, SpeechStart, Utterance
from jarvis.audio.sources import Pcm
from jarvis.orchestrator.segmenter import Segment, Segmenter, SpeechStarted
from tests.segmenter_rig import (
    FakeDeaf,
    FakeEndpointer,
    FakeScorer,
    make,
    run,
    run_events,
    utt,
)


class Ticker:
    """A callable clock that returns 0.0, 1.0, 2.0 ... on successive calls."""

    now: float = 0.0

    def __call__(self) -> float:
        value = self.now
        self.now += 1.0
        return value


def test_should_yield_speech_started_with_clock_value_when_speech_starts() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [SpeechStart(800)], [utt()]]
    scores = [0.0, 0.0, 0.0]
    deaf = [False, False, False]
    ticker = Ticker()
    segmenter, _, _ = make(script, scores, deaf, clock=ticker)
    events = run_events(segmenter, 3)
    assert events[0] == SpeechStarted(0.0)
    assert isinstance(events[1], Segment)
    assert len(events) == 2


def test_should_place_marker_before_segment_when_both_come_from_same_frame() -> None:
    script: list[list[SpeechStart | Utterance]] = [[SpeechStart(0), utt()]]
    scores = [0.0]
    deaf = [False]
    segmenter, _, _ = make(script, scores, deaf)
    events = run_events(segmenter, 1)
    assert len(events) == 2
    assert isinstance(events[0], SpeechStarted)
    assert isinstance(events[1], Segment)


def test_should_yield_no_events_when_no_speech() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], []]
    scores = [0.0, 0.0]
    deaf = [False, False]
    segmenter, _, _ = make(script, scores, deaf)
    events = run_events(segmenter, 2)
    assert events == []


def test_should_reset_scorer_once_after_deaf_stretch() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [], [], [], []]
    scores = [0.0] * 5
    deaf = [False, True, True, False, False]
    segmenter, _, scorer = make(script, scores, deaf)
    run_events(segmenter, 5)
    assert scorer.resets == 1
    assert len(scorer.calls) == 3


def test_should_reset_before_first_non_deaf_frame_is_scored() -> None:
    order: list[str] = []

    class OrderedScorer(FakeScorer):
        def reset(self) -> None:
            order.append("reset")
            super().reset()

        def score(self, frame: Pcm) -> float:
            order.append("score")
            return super().score(frame)

    endpointer = FakeEndpointer([[], []])
    scorer = OrderedScorer([0.0, 0.0])
    deaf = FakeDeaf([True, False])
    segmenter = Segmenter(cast(Endpointer, endpointer), scorer, deaf)
    run_events(segmenter, 2)
    assert order == ["reset", "score"]


def test_should_not_reset_when_never_deaf() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], []]
    scores = [0.0, 0.0]
    deaf = [False, False]
    segmenter, _, scorer = make(script, scores, deaf)
    run_events(segmenter, 2)
    assert scorer.resets == 0


def test_should_not_reset_when_always_deaf() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], []]
    scores = [0.0, 0.0]
    deaf = [True, True]
    segmenter, _, scorer = make(script, scores, deaf)
    run_events(segmenter, 2)
    assert scorer.resets == 0


def test_should_not_seed_next_segment_with_previous_score_after_reset() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [], [SpeechStart(500), utt()]]
    scores = [0.0, 0.0, 0.0]
    deaf = [True, False, False]
    segmenter, _, _ = make(script, scores, deaf)
    segments = run(segmenter, 3)
    assert len(segments) == 1
    assert segments[0].wake_score == 0.0
