import os

import numpy as np
import pytest

from jarvis import models
from jarvis.wake.detector import Backends, WakeDetector
from tests.audio_utils import voice

_OUTER_HOME = os.environ.get("JARVIS_HOME")


class FakeBackends:
    def __init__(self) -> None:
        self.mel_inputs: list[np.ndarray] = []
        self.embed_inputs: list[np.ndarray] = []
        self.classify_inputs: list[np.ndarray] = []
        self.embed_calls = 0

    def mel(self, audio: np.ndarray) -> np.ndarray:
        self.mel_inputs.append(audio)
        frames = -(-audio.shape[1] // 160) - 3
        return np.full((frames, 32), 10.0, dtype=np.float32)

    def embed(self, windows: np.ndarray) -> np.ndarray:
        self.embed_inputs.append(windows)
        self.embed_calls += 1
        return np.full((windows.shape[0], 96), float(self.embed_calls), dtype=np.float32)

    def classify(self, features: np.ndarray) -> float:
        self.classify_inputs.append(features)
        return float(features[0, -1, 0])

    def backends(self, n_features: int = 16) -> Backends:
        return Backends(self.mel, self.embed, self.classify, n_features)


def frame() -> np.ndarray:
    return np.zeros(1280, dtype=np.int16)


def make(fake: FakeBackends) -> WakeDetector:
    return WakeDetector(backends=fake.backends())


def test_should_prime_mel_and_embed_buffers_when_constructed() -> None:
    fake = FakeBackends()
    make(fake)
    assert fake.mel_inputs[0].shape == (1, 64000)
    assert fake.mel_inputs[0].dtype == np.float32
    assert fake.embed_inputs[0].shape == (41, 76, 32, 1)
    assert fake.embed_calls == 1
    assert len(fake.classify_inputs) == 0


def test_should_feed_mel_with_history_window_when_scoring_frames() -> None:
    fake = FakeBackends()
    detector = make(fake)
    detector.score(np.full(1280, 1, dtype=np.int16))
    detector.score(np.full(1280, 2, dtype=np.int16))
    detector.score(np.full(1280, 3, dtype=np.int16))
    assert fake.mel_inputs[1].shape == (1, 1280)
    assert fake.mel_inputs[2].shape == (1, 1760)
    assert fake.mel_inputs[3].shape == (1, 1760)
    third = fake.mel_inputs[3][0]
    assert np.all(third[:480] == 2.0)
    assert np.all(third[480:] == 3.0)


def test_should_embed_last_76_mel_rows_when_scoring() -> None:
    fake = FakeBackends()
    detector = make(fake)
    detector.score(frame())
    assert fake.embed_inputs[1].shape == (1, 76, 32, 1)
    assert fake.embed_inputs[1].dtype == np.float32
    assert fake.embed_inputs[1][0, -1, 0, 0] == 3.0


def test_should_classify_with_n_features_rows_when_configured() -> None:
    fake = FakeBackends()
    detector = WakeDetector(backends=fake.backends(n_features=8))
    detector.score(frame())
    assert fake.classify_inputs[0].shape == (1, 8, 96)
    assert fake.classify_inputs[0].dtype == np.float32


def test_should_return_zero_during_warmup_and_classifier_value_after() -> None:
    fake = FakeBackends()
    detector = make(fake)
    for _ in range(5):
        assert detector.score(frame()) == 0.0
    assert len(fake.classify_inputs) == 5
    assert detector.score(frame()) == 7.0
    assert detector.score(frame()) == 8.0


def test_should_restore_fresh_state_when_reset_called() -> None:
    fake = FakeBackends()
    detector = make(fake)
    for _ in range(7):
        detector.score(frame())
    detector.reset()
    for _ in range(5):
        assert detector.score(frame()) == 0.0
    assert detector.score(frame()) == float(fake.embed_calls)
    assert fake.mel_inputs[1 + 7].shape == (1, 1280)  # the priming call, 7 frames, then the first


def test_should_raise_value_error_when_frame_is_invalid() -> None:
    detector = make(FakeBackends())
    with pytest.raises(ValueError):
        detector.score(np.zeros(1279, dtype=np.int16))
    with pytest.raises(ValueError):
        detector.score(np.zeros(1280, dtype=np.float32))
    with pytest.raises(ValueError):
        detector.score(np.zeros((2, 640), dtype=np.int16))


def test_should_keep_rolling_buffer_shapes_when_scoring_many_frames() -> None:
    fake = FakeBackends()
    detector = make(fake)
    for _ in range(150):
        detector.score(frame())
    assert fake.classify_inputs[-1].shape == (1, 16, 96)
    assert fake.embed_inputs[-1].shape == (1, 76, 32, 1)
    assert fake.classify_inputs[-1][0, -1, 0] == 151.0


def test_should_produce_identical_priming_when_constructed_twice() -> None:
    fake1 = FakeBackends()
    fake2 = FakeBackends()
    make(fake1)
    make(fake2)
    assert np.array_equal(fake1.mel_inputs[0], fake2.mel_inputs[0])
    assert np.array_equal(fake1.embed_inputs[0], fake2.embed_inputs[0])


@pytest.mark.model
def test_should_score_silence_low_and_reset_to_a_fresh_state_when_real_models_are_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if _OUTER_HOME is None:
        pytest.skip("set JARVIS_HOME to a cache holding the oww models to run this test")
    monkeypatch.setenv("JARVIS_HOME", _OUTER_HOME)
    for name in ("oww-melspectrogram", "oww-embedding", "hey_jarvis_v0.1"):
        if not models.is_cached(models.get_spec(name)):
            pytest.skip(f"{name} is not cached; run `jarvis models fetch {name}`")
    detector = WakeDetector()
    for _ in range(40):
        assert detector.score(frame()) < 0.01
    detector.reset()
    audio = voice(2.0)
    frames = [audio[i * 1280 : (i + 1) * 1280] for i in range(len(audio) // 1280)]
    a = [detector.score(f) for f in frames]
    detector.reset()
    b = [detector.score(f) for f in frames]
    assert a == b
