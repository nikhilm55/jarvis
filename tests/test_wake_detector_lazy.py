import numpy as np
import numpy.typing as npt
import pytest

from jarvis.audio.sources import FRAME_SAMPLES
from jarvis.wake.detector import Backends, WakeDetector


class ContentBackends:
    """Deterministic fake backends whose outputs depend on input content."""

    def __init__(self, n_features: int = 16) -> None:
        self.n_features = n_features
        self.mel_calls = 0
        self.embed_calls = 0
        self.classify_calls = 0
        self._proj = np.random.default_rng(0).standard_normal((76 * 32, 96)) / 50.0
        self._coeff = np.random.default_rng(1).standard_normal((n_features, 96)) / 20.0

    def mel(self, x: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        self.mel_calls += 1
        n = x.shape[1]
        rows = -(-n // 160) - 3
        out = np.zeros((rows, 32), dtype=np.float32)
        scale = np.arange(1, 33, dtype=np.float32) / 1000.0
        for r in range(rows):
            out[r] = float(x[0, r * 160 : r * 160 + 400].mean()) * scale
        return out

    def embed(self, windows: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        self.embed_calls += 1
        b = windows.shape[0]
        flat = windows.reshape(b, -1).astype(np.float64)
        out = np.tanh(flat @ self._proj)
        return out.astype(np.float32)

    def classify(self, features: npt.NDArray[np.float32]) -> float:
        self.classify_calls += 1
        return float(np.tanh((features * self._coeff).sum()))

    def backends(self) -> Backends:
        return Backends(
            mel=self.mel, embed=self.embed, classify=self.classify, n_features=self.n_features
        )


def frames(count: int, seed: int) -> list[npt.NDArray[np.int16]]:
    rng = np.random.default_rng(seed)
    return [rng.integers(-3000, 3000, FRAME_SAMPLES).astype(np.int16) for _ in range(count)]


class State:
    """Mutable flag for the hot callable."""

    def __init__(self, hot: bool) -> None:
        self.hot = hot


GAP_LENGTHS = [0, 1, 5, 15, 16, 20, 28, 29, 40, 100]


@pytest.mark.parametrize("gap", GAP_LENGTHS)
def test_should_match_an_always_hot_detector_when_the_gap_is_replayed(gap: int) -> None:
    # Arrange
    full_backends = ContentBackends()
    lazy_backends = ContentBackends()
    state = State(True)
    full = WakeDetector(backends=full_backends.backends())
    lazy = WakeDetector(backends=lazy_backends.backends(), hot=lambda: state.hot)

    leading = frames(8, 10)
    cold = frames(gap, 20)
    trailing = frames(10, 30)

    for f in leading:
        full.score(f)
        lazy.score(f)

    state.hot = False
    cold_scores: list[float] = []
    for f in cold:
        cold_scores.append(full.score(f))
        lazy.score(f)

    state.hot = True
    hot_scores: list[float] = []
    for index, f in enumerate(trailing):
        expected = full.score(f)
        if index == 0:  # the frames just before the first hot one count with it
            expected = max([*cold_scores[-2:], expected])
        s_lazy = lazy.score(f)
        hot_scores.append(s_lazy)
        assert s_lazy == pytest.approx(expected, abs=1e-6)

    # Assert
    assert max(abs(s) for s in hot_scores) > 0.0


def test_should_run_no_model_when_the_frames_are_cold() -> None:
    # Arrange
    backends = ContentBackends()
    detector = WakeDetector(backends=backends.backends(), hot=lambda: False)
    mel_before = backends.mel_calls
    embed_before = backends.embed_calls
    classify_before = backends.classify_calls

    # Act
    cold = frames(10, 40)
    scores = [detector.score(f) for f in cold]

    # Assert
    assert backends.mel_calls == mel_before
    assert backends.embed_calls == embed_before
    assert backends.classify_calls == classify_before
    assert all(s == 0.0 for s in scores)


def test_should_count_cold_frames_toward_the_warm_up() -> None:
    # Arrange
    lazy_backends = ContentBackends()
    full_backends = ContentBackends()
    state = State(False)
    lazy = WakeDetector(backends=lazy_backends.backends(), hot=lambda: state.hot)
    full = WakeDetector(backends=full_backends.backends())

    cold = frames(6, 50)
    hot_frame = frames(1, 60)[0]

    for f in cold:
        lazy.score(f)
        full.score(f)
    state.hot = True

    # Act
    lazy_score = lazy.score(hot_frame)
    full_score = full.score(hot_frame)

    # Assert
    assert lazy_score != 0.0
    assert lazy_score == pytest.approx(full_score, abs=1e-6)


def test_should_replay_28_frames_in_one_embed_call_when_the_gap_is_long() -> None:
    # Arrange
    backends = ContentBackends()
    state = State(False)
    detector = WakeDetector(backends=backends.backends(), hot=lambda: state.hot)
    mel_before = backends.mel_calls
    embed_before = backends.embed_calls

    for f in frames(500, 70):
        detector.score(f)
    state.hot = True

    # Act
    detector.score(frames(1, 80)[0])

    # Assert
    assert backends.mel_calls - mel_before == 28
    assert backends.embed_calls - embed_before == 1


def test_should_forget_the_remembered_frames_when_reset() -> None:
    # Arrange
    backends = ContentBackends()
    state = State(False)
    detector = WakeDetector(backends=backends.backends(), hot=lambda: state.hot)

    for f in frames(10, 90):
        detector.score(f)

    detector.reset()
    state.hot = True
    mel_after_reset = backends.mel_calls

    # Act
    detector.score(frames(1, 100)[0])

    # Assert
    assert backends.mel_calls - mel_after_reset == 1


def test_should_score_every_frame_when_hot_is_none() -> None:
    # Arrange
    backends = ContentBackends()
    detector = WakeDetector(backends=backends.backends())
    mel_before = backends.mel_calls

    # Act
    for f in frames(5, 110):
        detector.score(f)

    # Assert
    assert backends.mel_calls - mel_before == 5


@pytest.mark.parametrize("n_features", [8, 16, 32, 39])
def test_should_match_an_always_hot_detector_when_the_classifier_reads_more_rows(
    n_features: int,
) -> None:
    full = WakeDetector(backends=ContentBackends(n_features).backends())
    state = State(True)
    lazy = WakeDetector(backends=ContentBackends(n_features).backends(), hot=lambda: state.hot)
    stream = frames(20 + 200 + 6, 7)
    for f in stream[:20]:
        full.score(f)
        lazy.score(f)
    state.hot = False
    cold_scores = [full.score(f) for f in stream[20:220]]
    for f in stream[20:220]:
        lazy.score(f)
    state.hot = True

    first = lazy.score(stream[220])
    expected = max([*cold_scores[-2:], full.score(stream[220])])
    rest = [(lazy.score(f), full.score(f)) for f in stream[221:]]

    assert first == pytest.approx(expected, abs=1e-6)
    assert [a for a, _ in rest] == pytest.approx([b for _, b in rest], abs=1e-6)
