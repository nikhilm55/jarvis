"""Subtle UI earcons rendered as soft sine tones with Hann fades."""

import numpy as np
import numpy.typing as npt

EARCON_RATE = 24000
EARCON_NAMES = ("wake", "done", "error", "thinking")

_NOTE_SPECS: dict[str, tuple[tuple[float, float], ...]] = {
    "wake": ((660.0, 0.07), (880.0, 0.07)),
    "done": ((880.0, 0.07), (660.0, 0.07)),
    "error": ((330.0, 0.09), (0.0, 0.04), (330.0, 0.09)),
    "thinking": ((520.0, 0.11),),
}


def _tone(freq: float, seconds: float) -> npt.NDArray[np.float32]:
    n = round(seconds * EARCON_RATE)
    t = np.arange(n, dtype=np.float64) / float(EARCON_RATE)
    if freq == 0.0:
        return np.zeros(n, dtype=np.float64).astype(np.float32)
    fade = round(0.012 * EARCON_RATE)
    fade = max(1, min(fade, n))
    envelope = np.ones(n, dtype=np.float64)
    ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade) / float(fade)))
    envelope[:fade] *= ramp
    envelope[-fade:] *= ramp[::-1]
    wave = 0.15 * np.sin(2.0 * np.pi * freq * t) * envelope
    return wave.astype(np.float32)


def earcon_samples(name: str) -> npt.NDArray[np.float32]:
    if name not in _NOTE_SPECS:
        known = ", ".join(EARCON_NAMES)
        raise ValueError(f"unknown earcon {name!r}; known: {known}")
    chunks = [_tone(f, s) for f, s in _NOTE_SPECS[name]]
    return np.concatenate(chunks)
