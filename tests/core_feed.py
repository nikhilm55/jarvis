"""A pushed-segment feed: an AudioSource and a Segmenter in one, for orchestrator tests."""

import queue
import threading
from collections.abc import Iterator

import numpy as np

from jarvis.audio import FRAME_SAMPLES
from jarvis.audio.sources import Pcm
from jarvis.orchestrator.segmenter import Segment


class Feed:
    """An AudioSource and a Segmenter in one: the test pushes segments, the capture thread reads."""

    def __init__(self) -> None:
        self._items: queue.Queue[Segment | Exception | None] = queue.Queue()
        self._current: Segment | None = None
        self.closed = threading.Event()

    def push(self, segment: Segment) -> None:
        self._items.put(segment)

    def end(self) -> None:
        self._items.put(None)

    def fail(self, error: Exception) -> None:
        self._items.put(error)

    def frames(self) -> Iterator[Pcm]:
        while True:
            item = self._items.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            self._current = item
            yield np.zeros(FRAME_SAMPLES, dtype=np.int16)

    def close(self) -> None:
        self.closed.set()
        self._items.put(None)

    def feed(self, frame: Pcm) -> list[Segment]:
        segment, self._current = self._current, None
        return [] if segment is None else [segment]

    def flush(self) -> list[Segment]:
        return []
