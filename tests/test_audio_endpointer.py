import numpy as np
import pytest

from jarvis import models
from jarvis.audio import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    Endpointer,
    Event,
    SpeechStart,
    Utterance,
)
from jarvis.audio.sources import Pcm
from jarvis.audio.vad import WINDOW_SAMPLES
from tests.audio_utils import quiet_noise, silence


class ScriptedVad:
    """One scripted probability per 512-sample window; records what it was given."""

    def __init__(self, probs: list[float]) -> None:
        self._probs = iter(probs)
        self.windows: list[Pcm] = []
        self.resets = 0

    def prob(self, window: Pcm) -> float:
        self.windows.append(window)
        return next(self._probs)

    def reset(self) -> None:
        self.resets += 1


def _run(probs: list[float], **kwargs: int) -> tuple[Endpointer, list[Event], ScriptedVad]:
    """Feed exactly one window of audio per scripted probability."""
    vad = ScriptedVad(probs)
    endpointer = Endpointer(vad, **kwargs)
    pcm = np.arange(len(probs) * WINDOW_SAMPLES, dtype=np.int16)
    return endpointer, endpointer.feed(pcm), vad


def _utterances(events: list[Event]) -> list[Utterance]:
    return [e for e in events if isinstance(e, Utterance)]


def test_should_end_utterance_when_trailing_silence_reaches_700_ms() -> None:
    _, events, _ = _run([0.0] * 10 + [0.9] * 20 + [0.0] * 22)  # 22 windows = 704 ms

    assert [type(e) for e in events] == [SpeechStart, Utterance]


def test_should_keep_utterance_open_when_silence_is_shorter_than_700_ms() -> None:
    _, events, _ = _run([0.0] * 10 + [0.9] * 20 + [0.0] * 21)  # 672 ms

    assert [type(e) for e in events] == [SpeechStart]


def test_should_not_end_utterance_when_speech_resumes_within_the_trailing_window() -> None:
    probs = [0.9] * 5 + [0.0] * 19 + [0.9] * 5 + [0.0] * 19  # 608 ms gaps, never 700

    _, events, _ = _run(probs)

    assert [type(e) for e in events] == [SpeechStart]


def test_should_honour_a_configured_trailing_ms() -> None:
    _, events, _ = _run([0.9] * 5 + [0.0] * 13, trailing_ms=400)  # 13 windows = 416 ms

    assert len(_utterances(events)) == 1


def test_should_start_on_0_5_but_continue_down_to_0_35() -> None:
    _, below, _ = _run([0.49] * 10)
    _, events, _ = _run([0.5] + [0.35] * 40 + [0.34] * 22)

    assert below == []
    assert [type(e) for e in events] == [SpeechStart, Utterance]
    assert len(_utterances(events)[0].pcm) == 63 * WINDOW_SAMPLES  # 0.35 was still speech


def test_should_end_at_the_cap_when_speech_never_stops() -> None:
    windows = 30 * SAMPLE_RATE // WINDOW_SAMPLES + 10

    _, events, _ = _run([0.9] * windows)

    (utterance,) = _utterances(events)
    assert len(utterance.pcm) == 30 * SAMPLE_RATE
    assert utterance.ended_at - utterance.started_at == pytest.approx(30.0)


def test_should_report_continuous_silence_before_speech_start() -> None:
    _, events, _ = _run([0.0] * 50 + [0.9] * 3)  # 1600 ms of silence

    assert events[0] == SpeechStart(silence_before_ms=1600)


def test_should_count_silence_before_a_second_utterance_from_the_end_of_the_first_speech() -> None:
    probs = [0.9] * 5 + [0.0] * 22 + [0.0] * 3 + [0.9] * 5  # 25 silent windows = 800 ms

    _, events, _ = _run(probs)

    assert events[2] == SpeechStart(silence_before_ms=800)


def test_should_prepend_exactly_1_5_s_of_pre_roll_and_time_the_utterance() -> None:
    lead_in = quiet_noise(3.2)
    audio = np.concatenate([lead_in, np.full(40 * WINDOW_SAMPLES, 5000, np.int16), silence(0.8)])
    vad = ScriptedVad([0.0] * 100 + [0.9] * 40 + [0.0] * 25)
    endpointer = Endpointer(vad)

    events = [
        e
        for i in range(0, len(audio), FRAME_SAMPLES)
        for e in endpointer.feed(audio[i:][:FRAME_SAMPLES])
    ]

    (utterance,) = _utterances(events)
    start = 100 * WINDOW_SAMPLES - int(1.5 * SAMPLE_RATE)
    end = 162 * WINDOW_SAMPLES
    assert np.array_equal(utterance.pcm, audio[start:end])
    assert utterance.started_at == pytest.approx(start / SAMPLE_RATE)
    assert utterance.ended_at == pytest.approx(end / SAMPLE_RATE)


def test_should_lose_no_samples_when_rebuffering_1280_frames_into_512_windows() -> None:
    vad = ScriptedVad([0.0] * 17)
    endpointer = Endpointer(vad)
    pcm = np.arange(7 * FRAME_SAMPLES, dtype=np.int16)

    for i in range(0, len(pcm), FRAME_SAMPLES):
        endpointer.feed(pcm[i : i + FRAME_SAMPLES])

    assert len(vad.windows) == 17  # 8960 samples = 17 windows + 256 pending
    assert all(len(w) == WINDOW_SAMPLES for w in vad.windows)
    assert np.array_equal(np.concatenate(vad.windows), pcm[: 17 * WINDOW_SAMPLES])


def test_should_close_an_open_utterance_when_flushed() -> None:
    endpointer, events, _ = _run([0.0] * 4 + [0.9] * 10)

    (flushed,) = endpointer.flush()

    assert [type(e) for e in events] == [SpeechStart]
    assert isinstance(flushed, Utterance) and len(flushed.pcm) == 14 * WINDOW_SAMPLES
    assert endpointer.flush() == []


def test_should_reset_the_vad_after_each_utterance() -> None:
    _, _, vad = _run([0.9] * 5 + [0.0] * 22)

    assert vad.resets == 1


def test_should_reject_frames_that_are_not_1d_int16() -> None:
    endpointer = Endpointer(ScriptedVad([]))

    with pytest.raises(ValueError, match="int16"):
        endpointer.feed(np.zeros(FRAME_SAMPLES, dtype=np.float32))


def test_should_pin_the_silero_model_to_a_commit_and_a_sha256() -> None:
    spec = models.get_spec("silero-vad")

    assert "/snakers4/silero-vad/" in spec.url and spec.url.endswith("/silero_vad.onnx")
    assert len(spec.sha256) == 64
    assert len(spec.url.split("/silero-vad/")[1].split("/")[0]) == 40  # a commit, not a branch
