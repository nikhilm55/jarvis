"""Tests for jarvis.orchestrator.capture."""

import asyncio
import threading
from collections.abc import Iterator

import numpy as np

from jarvis.audio import FRAME_SAMPLES, Utterance
from jarvis.audio.sources import Pcm
from jarvis.orchestrator.capture import Capture, CaptureItem, SourceEnded, SourceFailed
from jarvis.orchestrator.segmenter import Segment, SegmentEvent, SpeechStarted


def seg(tag: float) -> Segment:
    return Segment(
        Utterance(np.zeros(FRAME_SAMPLES, dtype=np.int16), tag, tag + 1.0), 800, 0.5, False
    )


class ListSource:
    def __init__(self, n: int, fail_at: int | None = None) -> None:
        self.n = n
        self.fail_at = fail_at
        self.closed = False

    def frames(self) -> Iterator[Pcm]:
        for i in range(self.n):
            if self.fail_at is not None and i == self.fail_at:
                raise RuntimeError("mic broke")
            yield np.zeros(FRAME_SAMPLES, dtype=np.int16)

    def close(self) -> None:
        self.closed = True


class BlockingSource:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.yielded = 0
        self.closed = False

    def frames(self) -> Iterator[Pcm]:
        while not self._stop.is_set():
            self.yielded += 1
            yield np.zeros(FRAME_SAMPLES, dtype=np.int16)
            self._stop.wait(0.005)

    def close(self) -> None:
        self._stop.set()
        self.closed = True


class ScriptedSegmenter:
    def __init__(
        self,
        per_frame: dict[int, list[SegmentEvent]],
        flushed: list[Segment] | None = None,
        fail_on_frame: int | None = None,
    ) -> None:
        self.per_frame = per_frame
        self.flushed = flushed if flushed is not None else []
        self.fail_on_frame = fail_on_frame
        self.counter = 0

    def feed(self, frame: Pcm) -> list[SegmentEvent]:
        self.counter += 1
        if self.fail_on_frame is not None and self.counter == self.fail_on_frame:
            raise ValueError("bad frame")
        return self.per_frame.get(self.counter - 1, [])

    def flush(self) -> list[Segment]:
        return self.flushed


async def frames_seen(source: BlockingSource, count: int) -> None:
    async def spin() -> None:
        while source.yielded < count:
            await asyncio.sleep(0.005)

    await asyncio.wait_for(spin(), 2)


async def collect(queue: asyncio.Queue[CaptureItem], count: int) -> list[CaptureItem]:
    items: list[CaptureItem] = []
    for _ in range(count):
        items.append(await asyncio.wait_for(queue.get(), 2))
    return items


def test_should_post_segments_in_order_and_source_ended_when_source_runs_out() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = ListSource(4)
        segmenter = ScriptedSegmenter({1: [seg(1.0)], 3: [seg(3.0), seg(3.5)]})
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            items = await collect(queue, 4)
            assert items[0] is segmenter.per_frame[1][0]
            assert items[1] is segmenter.per_frame[3][0]
            assert items[2] is segmenter.per_frame[3][1]
            assert isinstance(items[3], SourceEnded)
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_post_flush_segments_before_source_ended_when_source_runs_out() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = ListSource(1)
        segmenter = ScriptedSegmenter({}, flushed=[seg(9.0)])
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            items = await collect(queue, 2)
            assert items[0] is segmenter.flushed[0]
            assert isinstance(items[1], SourceEnded)
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_post_source_failed_when_source_raises() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = ListSource(3, fail_at=2)
        segmenter = ScriptedSegmenter({0: [seg(0.0)]})
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            items = await collect(queue, 2)
            assert items[0] is segmenter.per_frame[0][0]
            assert isinstance(items[1], SourceFailed)
            assert str(items[1].error) == "mic broke"
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_post_source_failed_when_segmenter_raises() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = ListSource(3)
        segmenter = ScriptedSegmenter({}, fail_on_frame=2)
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            item = await asyncio.wait_for(queue.get(), 2)
            assert isinstance(item, SourceFailed)
            assert str(item.error) == "bad frame"
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_end_thread_when_stop_called_on_infinite_source() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = BlockingSource()
        segmenter = ScriptedSegmenter({})
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            await frames_seen(source, 3)
            capture.stop()
            assert await asyncio.to_thread(capture.join, 2) is True
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_not_post_segments_after_stop_when_source_is_infinite() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = BlockingSource()
        segmenter = ScriptedSegmenter({i: [seg(float(i))] for i in range(100)})
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            await frames_seen(source, 3)
            capture.stop()
            assert await asyncio.to_thread(capture.join, 2) is True
            size_before = queue.qsize()
            await asyncio.sleep(0.05)
            assert queue.qsize() == size_before
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_use_daemon_thread_named_jarvis_capture_when_started() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        source = BlockingSource()
        segmenter = ScriptedSegmenter({})
        capture = Capture(source, segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            await frames_seen(source, 1)
            threads = [t for t in threading.enumerate() if t.name == "jarvis-capture"]
            assert len(threads) == 1
            assert threads[0].daemon is True
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())


def test_should_post_the_speech_started_marker_in_order_with_the_segments() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[CaptureItem] = asyncio.Queue()
        marker = SpeechStarted(12.5)
        segmenter = ScriptedSegmenter({0: [marker], 2: [seg(2.0)]})
        capture = Capture(ListSource(3), segmenter, asyncio.get_running_loop(), queue.put_nowait)
        try:
            capture.start()
            items = await collect(queue, 3)
            assert items[0] is marker
            assert isinstance(items[1], Segment)
            assert isinstance(items[2], SourceEnded)
        finally:
            capture.stop()
            await asyncio.to_thread(capture.join, 2)

    asyncio.run(scenario())
