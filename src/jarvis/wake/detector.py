"""Re-implements openWakeWord 0.6.0's ONNX wake detector directly on onnxruntime.

Reproduces the upstream streaming path (``AudioFeatures._streaming_features`` +
``Model.predict``) exactly, without the ``openwakeword`` dependency (ADR-0010).
Scores match upstream to ~1e-3 (checked by scripts/check_wake_parity.py).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import onnxruntime

from jarvis.audio.sources import FRAME_SAMPLES, Pcm
from jarvis.config import WakeSettings
from jarvis.models import ensure

MelFn = Callable[[npt.NDArray[np.float32]], npt.NDArray[np.float32]]
EmbedFn = Callable[[npt.NDArray[np.float32]], npt.NDArray[np.float32]]
ClassifyFn = Callable[[npt.NDArray[np.float32]], float]

_MEL_BINS = 32
_MEL_CONTEXT = 480
_WINDOW = 76
_STRIDE = 8
_EMBED_DIM = 96
_MEL_MAX_ROWS = 970
_FEATURE_MAX_ROWS = 120
_WARMUP_FRAMES = 5
_PRIME_SAMPLES = 64000
_PRIME_SEED = 0


@dataclass(frozen=True)
class Backends:
    """Pluggable ONNX inference backends for the wake detector."""

    mel: MelFn
    embed: EmbedFn
    classify: ClassifyFn
    n_features: int = 16


def _session(name: str) -> onnxruntime.InferenceSession:
    """Create a single-threaded CPU ONNX inference session for a model."""
    options = onnxruntime.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    return onnxruntime.InferenceSession(
        str(ensure(name)), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _onnx_backends(model_name: str) -> Backends:
    """Build real ONNX backends for the mel, embedding, and classifier models."""
    mel_session = _session("oww-melspectrogram")
    embed_session = _session("oww-embedding")
    clf_session = _session(model_name)

    mel_name = mel_session.get_inputs()[0].name
    embed_name = embed_session.get_inputs()[0].name
    clf_name = clf_session.get_inputs()[0].name

    def mel(x: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        return np.asarray(mel_session.run(None, {mel_name: x})[0], dtype=np.float32).reshape(-1, 32)

    def embed(w: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        return np.asarray(embed_session.run(None, {embed_name: w})[0], dtype=np.float32).reshape(
            w.shape[0], _EMBED_DIM
        )

    def classify(f: npt.NDArray[np.float32]) -> float:
        return float(np.asarray(clf_session.run(None, {clf_name: f})[0]).reshape(-1)[0])

    n_features = int(clf_session.get_inputs()[0].shape[1])
    return Backends(mel=mel, embed=embed, classify=classify, n_features=n_features)


class WakeDetector:
    """Streaming wake-word detector scoring 80 ms frames with a 5-frame warm-up."""

    def __init__(self, model_name: str | None = None, *, backends: Backends | None = None) -> None:
        self._backends = (
            backends if backends is not None else _onnx_backends(model_name or WakeSettings().model)
        )
        self._primed = self._prime()
        self.reset()

    def _prime(self) -> npt.NDArray[np.float32]:
        """Generate the initial feature buffer from 4 s of seeded random noise."""
        rng = np.random.default_rng(_PRIME_SEED)
        noise = rng.integers(-1000, 1000, _PRIME_SAMPLES).astype(np.int16)
        spec = self._melspec(noise)
        windows = [
            spec[i : i + _WINDOW]
            for i in range(0, spec.shape[0], _STRIDE)
            if i + _WINDOW <= spec.shape[0]
        ]
        batch = np.expand_dims(np.array(windows), axis=-1).astype(np.float32)
        return self._backends.embed(batch)

    def _melspec(self, samples: Pcm) -> npt.NDArray[np.float32]:
        """Compute raw mel spectrogram features with the upstream transform."""
        x = samples.astype(np.float32)[None, :]
        return np.asarray(self._backends.mel(x) / 10 + 2, dtype=np.float32)

    def reset(self) -> None:
        """Reset internal buffers to their initial state."""
        self._history = np.empty(0, dtype=np.int16)
        self._mel: npt.NDArray[Any] = np.ones((_WINDOW, _MEL_BINS))
        self._features = self._primed.copy()
        self._frames_scored = 0

    def score(self, frame: Pcm) -> float:
        """Score one 80 ms frame; returns 0.0 during the first 5 warm-up frames."""
        if frame.dtype != np.int16 or frame.shape != (FRAME_SAMPLES,):
            raise ValueError(
                f"expected {FRAME_SAMPLES} int16 samples, got {frame.dtype} {frame.shape}"
            )
        self._history = np.concatenate((self._history, frame))[-(FRAME_SAMPLES + _MEL_CONTEXT) :]
        self._mel = np.vstack((self._mel, self._melspec(self._history)))[-_MEL_MAX_ROWS:]
        window = self._mel[-_WINDOW:].astype(np.float32)[None, :, :, None]
        embedding = self._backends.embed(window)
        self._features = np.vstack((self._features, embedding))[-_FEATURE_MAX_ROWS:]
        features = self._features[-self._backends.n_features :].astype(np.float32)[None, :, :]
        value = self._backends.classify(features)
        self._frames_scored += 1
        return 0.0 if self._frames_scored <= _WARMUP_FRAMES else value
