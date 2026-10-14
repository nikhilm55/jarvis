"""The frame loop on its own thread, so VAD and wake scoring never block the loop (FR-ACT-02)."""

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.audio import AudioSource
from jarvis.orchestrator.ports import SegmenterPort
from jarvis.orchestrator.segmenter import Segment

__all__ = ["Capture", "CaptureItem", "SourceEnded", "SourceFailed"]


@dataclass(frozen=True)
class SourceEnded:
    """The audio source ran out (end of a WAV file)."""


@dataclass(frozen=True)
class SourceFailed:
    """The audio source or the segmenter raised."""

    error: Exception


CaptureItem = Segment | SourceEnded | SourceFailed


class Capture:
    """Runs the frame loop on a dedicated thread and posts items to the event loop."""

    def __init__(
        self,
        source: AudioSource,
        segmenter: SegmenterPort,
        loop: asyncio.AbstractEventLoop,
        sink: Callable[[CaptureItem], None],
    ) -> None:
        """Store dependencies and prepare the worker thread."""
        self._source = source
        self._segmenter = segmenter
        self._loop = loop
        self._sink = sink
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._run, name="jarvis-capture", daemon=True)

    def start(self) -> None:
        """Start the capture thread."""
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to stop and close the source."""
        self._halt.set()
        self._source.close()

    def join(self, timeout: float) -> bool:
        """Wait for the thread to finish and report whether it is still alive."""
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self) -> None:
        """Consume frames, feed the segmenter, and post results or failures."""
        try:
            for frame in self._source.frames():
                if self._halt.is_set():
                    return
                for segment in self._segmenter.feed(frame):
                    self._post(segment)
            if self._halt.is_set():
                return
            for segment in self._segmenter.flush():
                self._post(segment)
            self._post(SourceEnded())
        except Exception as error:
            # The source, the VAD and the wake model are all allowed to fail;
            # the failure is handed to the event loop.
            if not self._halt.is_set():
                self._post(SourceFailed(error))

    def _post(self, item: CaptureItem) -> None:
        """Thread-safely schedule the sink callback on the event loop."""
        try:
            self._loop.call_soon_threadsafe(self._sink, item)
        except RuntimeError:
            # The loop is closed.
            self._halt.set()
