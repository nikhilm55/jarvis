import os

import numpy as np
import pytest

from jarvis import models
from jarvis.audio import FRAME_SAMPLES, Endpointer, SileroVad, SpeechStart, Utterance
from tests.audio_utils import silence, tone, voice

_OUTER_HOME = os.environ.get("JARVIS_HOME")  # the autouse fixture replaces it per test


@pytest.mark.model
def test_should_detect_speech_with_the_real_silero_model(monkeypatch: pytest.MonkeyPatch) -> None:
    if _OUTER_HOME is None:
        pytest.skip("set JARVIS_HOME to a cache holding silero-vad to run this test")
    monkeypatch.setenv("JARVIS_HOME", _OUTER_HOME)
    if not models.is_cached(models.get_spec("silero-vad")):
        pytest.skip("silero-vad is not cached; run `jarvis models fetch silero-vad`")
    audio = np.concatenate([silence(0.5), tone(1.0), silence(0.5), voice(2.0), silence(1.2)])
    endpointer = Endpointer(SileroVad())

    events = [
        e
        for i in range(0, len(audio), FRAME_SAMPLES)
        for e in endpointer.feed(audio[i:][:FRAME_SAMPLES])
    ]

    assert [type(e) for e in events] == [SpeechStart, Utterance]
    start, utterance = events
    assert (
        isinstance(start, SpeechStart) and start.silence_before_ms >= 1900
    )  # the tone is not speech
    assert (
        isinstance(utterance, Utterance) and 2.0 <= utterance.ended_at - utterance.started_at <= 5.0
    )
