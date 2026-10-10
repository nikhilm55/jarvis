"""RAM-only ring buffer of the most recent audio (FR-ACT-02, FR-AUD-05: never touches disk)."""

from collections import deque

import numpy as np

from jarvis.audio.sources import SAMPLE_RATE, Pcm


class PreRoll:
    """Keeps the last `seconds` of audio; chunks of any length may be pushed."""

    def __init__(self, seconds: float = 1.5) -> None:
        self._capacity = int(seconds * SAMPLE_RATE)
        self._chunks: deque[Pcm] = deque()
        self._size = 0

    def push(self, frame: Pcm) -> None:
        self._chunks.append(frame)
        self._size += len(frame)
        while self._chunks and self._size - len(self._chunks[0]) >= self._capacity:
            self._size -= len(self._chunks.popleft())

    def snapshot(self) -> Pcm:
        """The buffered audio, oldest first, at most `seconds` long."""
        if not self._chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(self._chunks)[-self._capacity :]

    def clear(self) -> None:
        self._chunks.clear()
        self._size = 0
