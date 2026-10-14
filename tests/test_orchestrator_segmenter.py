"""Tests for jarvis.orchestrator.segmenter."""

from jarvis.audio import SpeechStart, Utterance
from tests.segmenter_rig import make, run, utt


def test_should_return_no_segments_when_no_speech_events_occur() -> None:
    segmenter, endpointer, _ = make([[], [], []], [0.0, 0.0, 0.0], [False, False, False])
    segments = run(segmenter, 3)
    assert segments == []
    assert len(endpointer.frames) == 3


def test_should_produce_segment_with_correct_silence_when_speech_start_and_utterance_occur() -> (
    None
):
    closing = utt()
    script: list[list[SpeechStart | Utterance]] = [[], [], [SpeechStart(800)], [], [closing]]
    segmenter, _, _ = make(script, [0.0] * 5, [False] * 5)
    segments = run(segmenter, 5)
    assert len(segments) == 1
    assert segments[0].silence_before_ms == 800
    assert segments[0].utterance is closing


def test_should_use_peak_score_when_multiple_scores_occur_during_segment() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [], [SpeechStart(0)], [], [utt()]]
    segmenter, _, _ = make(script, [0.0, 0.0, 0.02, 0.5, 0.1], [False] * 5)
    segments = run(segmenter, 5)
    assert len(segments) == 1
    assert segments[0].wake_score == 0.5


def test_should_include_previous_frame_score_when_speech_start_occurs() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [SpeechStart(0)], [utt()]]
    segmenter, _, _ = make(script, [0.9, 0.0, 0.0], [False] * 3)
    segments = run(segmenter, 3)
    assert len(segments) == 1
    assert segments[0].wake_score == 0.9


def test_should_not_include_score_two_frames_before_when_speech_start_occurs() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [], [SpeechStart(0)], [utt()]]
    segmenter, _, _ = make(script, [0.9, 0.0, 0.0, 0.0], [False] * 4)
    segments = run(segmenter, 4)
    assert len(segments) == 1
    assert segments[0].wake_score == 0.0


def test_should_keep_separate_peaks_when_two_segments_occur_in_sequence() -> None:
    script: list[list[SpeechStart | Utterance]] = [
        [SpeechStart(0)],
        [utt()],
        [SpeechStart(0)],
        [utt()],
    ]
    segmenter, _, _ = make(script, [0.7, 0.0, 0.1, 0.0], [False] * 4)
    segments = run(segmenter, 4)
    assert len(segments) == 2
    assert segments[0].wake_score == 0.7
    assert segments[1].wake_score == 0.1


def test_should_mark_segment_tainted_when_deaf_during_segment() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [SpeechStart(0)], [], [utt()], []]
    segmenter, _, _ = make(script, [0.0] * 5, [False, False, True, False, False])
    segments = run(segmenter, 5)
    assert len(segments) == 1
    assert segments[0].tainted is True


def test_should_not_mark_segment_tainted_when_deaf_only_before_speech_start() -> None:
    script: list[list[SpeechStart | Utterance]] = [[], [], [SpeechStart(0)], [], [utt()]]
    segmenter, _, _ = make(script, [0.0] * 5, [True, False, False, False, False])
    segments = run(segmenter, 5)
    assert len(segments) == 1
    assert segments[0].tainted is False


def test_should_not_call_scorer_when_deaf() -> None:
    segmenter, _, scorer = make([[], [], []], [0.0, 0.0, 0.0], [True, True, False])
    run(segmenter, 3)
    assert len(scorer.calls) == 1


def test_should_return_segment_on_flush_when_segment_is_open() -> None:
    script: list[list[SpeechStart | Utterance]] = [[SpeechStart(500)]]
    segmenter, _, _ = make(script, [0.0], [False], flushed=[utt()])
    run(segmenter, 1)
    segments = segmenter.flush()
    assert len(segments) == 1
    assert segments[0].silence_before_ms == 500


def test_should_return_empty_list_on_flush_when_nothing_is_open() -> None:
    segmenter, _, _ = make([], [], [])
    segments = segmenter.flush()
    assert segments == []


def test_should_mark_segment_tainted_when_deaf_only_on_the_closing_frame() -> None:
    script: list[list[SpeechStart | Utterance]] = [[SpeechStart(0)], [utt()]]
    segmenter, _, _ = make(script, [0.0, 0.0], [False, True])
    segments = run(segmenter, 2)
    assert segments[0].tainted is True


def test_should_count_the_closing_frame_score_when_the_utterance_closes() -> None:
    script: list[list[SpeechStart | Utterance]] = [[SpeechStart(0)], [utt()]]
    segmenter, _, _ = make(script, [0.0, 0.8], [False, False])
    segments = run(segmenter, 2)
    assert segments[0].wake_score == 0.8
