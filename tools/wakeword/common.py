"""Shared paths and helpers for the wake-word pipeline (dev-only, never imported by src/)."""

from __future__ import annotations

import hashlib
import json
import os
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("WAKEWORD_DATA", HERE / "data"))
LOGS = DATA / "logs"
RATE = 16_000
FRAME = 1280  # one 80 ms hop, the product's frame size
M0A = Path.home() / "Jarvis" / "spikes" / "M0a-wake-word" / "data"  # read-only held-out set
MAX_DOWNLOAD_BYTES = 2_000_000_000  # R73: stop and ask before downloading more than this


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_wav(path: Path) -> np.ndarray:
    """A 16 kHz mono 16-bit wav as float32 in [-1, 1]."""
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != RATE or handle.getnchannels() != 1:
            raise ValueError(f"{path}: expected 16 kHz mono")
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: Path, audio: np.ndarray) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm.tobytes())
