import numpy as np
import pytest

from jarvis.wake.detector import WakeDetector
from tests.test_wake_detector import FakeBackends


class LongMelFakeBackends(FakeBackends):
    def mel(self, audio: np.ndarray) -> np.ndarray:
        self.mel_inputs.append(audio)
        return np.full((1200, 32), 10.0, dtype=np.float32)


def make_with_n_features(fake: FakeBackends, n_features: int) -> WakeDetector:
    return WakeDetector(backends=fake.backends(n_features=n_features))


def test_should_construct_when_n_features_fits() -> None:
    fake = FakeBackends()
    make_with_n_features(fake, 16)
    fake2 = FakeBackends()
    make_with_n_features(fake2, 39)


def test_should_raise_when_n_features_exceeds_primed_embeddings() -> None:
    fake = FakeBackends()
    with pytest.raises(ValueError, match="n_features"):
        make_with_n_features(fake, 40)


def test_should_raise_when_n_features_exceeds_feature_buffer() -> None:
    fake = LongMelFakeBackends()
    with pytest.raises(ValueError, match="n_features"):
        make_with_n_features(fake, 119)
    fake2 = LongMelFakeBackends()
    make_with_n_features(fake2, 118)
