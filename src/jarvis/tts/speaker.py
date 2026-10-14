"""Speaker: queue-based TTS orchestrator with cancellation and streaming."""

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.config import TtsSettings
from jarvis.log import get_logger
from jarvis.tts.earcons import EARCON_RATE, earcon_samples
from jarvis.tts.engines import (
    AudioEngine,
    DirectEngine,
    Engine,
    Pcm,
    default_engine,
)
from jarvis.tts.handle import SpeechHandle
from jarvis.tts.sink import BLOCK_S, Sink, SoundDeviceSink
from jarvis.tts.text import split_sentences

logger = get_logger(__name__)

__all__ = ["Speaker", "SpeechHandle"]


@dataclass(frozen=True)
class _Job:
    """Internal unit of work handed to the worker thread."""

    handle: SpeechHandle
    text: str
    clip: Pcm | None


class Speaker:
    """Serialises TTS jobs on a worker thread with streaming playback."""

    def __init__(
        self,
        settings: TtsSettings | None = None,
        *,
        engine_factory: Callable[[], Engine] | None = None,
        sink_factory: Callable[[int], Sink] = SoundDeviceSink,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings if settings is not None else TtsSettings()
        self._engine_factory = (
            engine_factory
            if engine_factory is not None
            else (lambda: default_engine(self._settings))
        )
        self._sink_factory = sink_factory
        self._clock = clock
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._engine: Engine | None = None
        self._synth: threading.Thread | None = None
        self._current: SpeechHandle | None = None
        self._lock = threading.Lock()
        self._synth_lock = threading.Lock()
        self._closed = False

    def say(self, text: str) -> SpeechHandle:
        """Queue a text-to-speech job and return its handle."""
        handle = SpeechHandle(text, self._clock)
        if not text.strip():
            handle._finish()
            return handle
        self._enqueue(_Job(handle, text, None))
        return handle

    def earcon(self, name: str) -> SpeechHandle:
        """Queue an earcon (pre-rendered clip) and return its handle."""
        clip = earcon_samples(name)
        handle = SpeechHandle(name, self._clock)
        self._enqueue(_Job(handle, name, clip))
        return handle

    def close(self) -> None:
        """Stop the worker, cancel in-flight work, and release resources."""
        with self._lock:
            self._closed = True
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                if job is not None:
                    job.handle.cancel()
            self._jobs.put(None)
            current = self._current
            thread = self._thread
            synth = self._synth
        if current is not None:
            current.cancel()
        if thread is not None:
            thread.join(timeout=5)
        if synth is not None:
            synth.join(timeout=5)

    def _enqueue(self, job: _Job) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("speaker is closed")
            self._jobs.put(job)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._worker,
                    name="jarvis-tts",
                    daemon=True,
                )
                self._thread.start()

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            skip = False
            with self._lock:
                if self._closed or job.handle.cancelled:
                    job.handle.cancel()
                    skip = True
                else:
                    self._current = job.handle
            if skip:
                continue
            try:
                self._run(job)
            except Exception:
                logger.exception("speech job failed")
                job.handle._fail()
            else:
                job.handle._finish()
            finally:
                with self._lock:
                    self._current = None

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._engine_factory()
        return self._engine

    def _run(self, job: _Job) -> None:
        if job.clip is not None:
            self._play_earcon(job.handle, job.clip)
            return
        engine = self._get_engine()
        if isinstance(engine, DirectEngine):
            self._speak_direct(job, engine)
            return
        if isinstance(engine, AudioEngine):
            self._speak_audio(job, engine)
            return
        raise TypeError(f"unsupported engine type: {type(engine).__name__}")

    def _speak_direct(self, job: _Job, engine: DirectEngine) -> None:
        handle = job.handle
        handle._register_cancel(engine.cancel)
        handle._note_first_audio()
        engine.speak(job.text)
        handle._clear_cancel()

    def _speak_audio(self, job: _Job, engine: AudioEngine) -> None:
        handle = job.handle
        clips: queue.Queue[Pcm | Exception | None] = queue.Queue(maxsize=1)
        stop = threading.Event()
        self._synth = threading.Thread(
            target=_synthesise_into,
            args=(
                _locked(self._synth_lock, engine.synthesize),
                split_sentences(job.text),
                clips,
                stop,
            ),
            name="jarvis-tts-synth",
            daemon=True,
        )
        self._synth.start()
        try:
            sink = self._sink_factory(engine.sample_rate)
            self._play_clips(clips, sink, engine.sample_rate, handle)
        finally:
            stop.set()

    def _play_clips(
        self,
        clips: queue.Queue[Pcm | Exception | None],
        sink: Sink,
        rate: int,
        handle: SpeechHandle,
    ) -> None:
        block_size = max(1, int(rate * BLOCK_S))
        aborted = False
        try:
            while True:
                if handle.cancelled:
                    aborted = True
                    break
                try:
                    clip = clips.get(timeout=0.02)
                except queue.Empty:
                    continue
                if clip is None:
                    break
                if isinstance(clip, Exception):
                    raise clip
                for block in _chunks(clip, block_size):
                    if handle.cancelled:
                        aborted = True
                        break
                    handle._note_first_audio()
                    sink.write(block)
                if handle.cancelled:
                    aborted = True
                    break
        finally:
            try:
                if aborted:
                    sink.abort()
            finally:
                sink.close()

    def _play_earcon(self, handle: SpeechHandle, clip: Pcm) -> None:
        sink = self._sink_factory(EARCON_RATE)
        self._play_clips(_single_queue(clip), sink, EARCON_RATE, handle)


def _single_queue(clip: Pcm) -> queue.Queue[Pcm | Exception | None]:
    q: queue.Queue[Pcm | Exception | None] = queue.Queue()
    q.put(clip)
    q.put(None)
    return q


def _put(
    clips: queue.Queue[Pcm | Exception | None],
    item: Pcm | Exception | None,
    stop: threading.Event,
) -> bool:
    """Hand `item` to the player; False once `stop` is set (the player has gone away)."""
    while not stop.is_set():
        try:
            clips.put(item, timeout=0.02)
        except queue.Full:
            continue
        return True
    return False


def _synthesise_into(
    synthesize: Callable[[str], Pcm],
    sentences: list[str],
    clips: queue.Queue[Pcm | Exception | None],
    stop: threading.Event,
) -> None:
    """Synthesise sentence by sentence, at most one clip ahead of the player."""
    for sentence in sentences:
        if stop.is_set():
            return
        try:
            item: Pcm | Exception = synthesize(sentence)
        except Exception as error:
            _put(clips, error, stop)
            return
        if not _put(clips, item, stop):
            return
    _put(clips, None, stop)


def _chunks(clip: Pcm, size: int) -> list[Pcm]:
    return [clip[i : i + size] for i in range(0, len(clip), size)]


def _locked(
    lock: threading.Lock,
    synthesize: Callable[[str], Pcm],
) -> Callable[[str], Pcm]:
    """Return a wrapper that serialises calls to `synthesize` under `lock`."""

    def _call(text: str) -> Pcm:
        with lock:
            return synthesize(text)

    return _call
