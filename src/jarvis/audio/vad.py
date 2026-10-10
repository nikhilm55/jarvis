"""Voice-activity detection: the `Vad` protocol and the Silero v5 ONNX implementation."""

from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
import onnxruntime

from jarvis.audio.sources import SAMPLE_RATE, Pcm
from jarvis.models import ensure

WINDOW_SAMPLES = 512  # the only window size Silero v5 accepts at 16 kHz
CONTEXT_SAMPLES = 64  # the v5 model wants the previous window's last 64 samples prepended


class Vad(Protocol):
    def prob(self, window: Pcm) -> float:
        """Speech probability (0..1) of one 512-sample window."""
        ...

    def reset(self) -> None: ...


class SileroVad:
    """Silero VAD v5 on onnxruntime (CPU, one intra-op thread), keeping its recurrent state."""

    def __init__(self, model_path: Path | None = None) -> None:
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            str(model_path or ensure("silero-vad")),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._rate = np.array(SAMPLE_RATE, dtype=np.int64)
        self._state: npt.NDArray[np.float32]
        self._context: npt.NDArray[np.float32]
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    def prob(self, window: Pcm) -> float:
        if window.shape != (WINDOW_SAMPLES,):
            raise ValueError(f"Silero needs {WINDOW_SAMPLES}-sample windows, got {window.shape}")
        samples = window.astype(np.float32).reshape(1, -1) / 32768.0
        model_input = np.concatenate([self._context, samples], axis=1)
        output, state = self._session.run(
            None, {"input": model_input, "state": self._state, "sr": self._rate}
        )
        self._state = state
        self._context = model_input[:, -CONTEXT_SAMPLES:]
        return float(output[0, 0])
