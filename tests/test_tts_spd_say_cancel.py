import subprocess
import threading
from typing import Any

from jarvis.tts.engines import SpdSayEngine


class FakeProc:
    def __init__(self, finished: bool = False) -> None:
        self.done = threading.Event()
        self.terminated = False
        if finished:
            self.done.set()

    def wait(self, timeout: float | None = None) -> int:
        self.done.wait(timeout if timeout is not None else 5.0)
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.done.set()


class RecordingPopen:
    def __init__(self, proc: FakeProc) -> None:
        self.proc = proc
        self.started = threading.Event()
        self.calls: list[list[str]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeProc:
        self.calls.append(list(args[0]))
        self.started.set()
        return self.proc


class BlockingPopen:
    def __init__(self, proc: FakeProc) -> None:
        self.proc = proc
        self.spawning = threading.Event()
        self.release = threading.Event()
        self.calls: list[list[str]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeProc:
        self.calls.append(list(args[0]))
        self.spawning.set()
        self.release.wait(5.0)
        return self.proc


class StubRun:
    def __init__(self, exc: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.exc = exc

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append(list(args[0]))
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(args=args[0], returncode=0)


def test_should_terminate_and_not_raise_when_spd_say_cancel_times_out() -> None:
    proc = FakeProc(finished=False)
    popen = RecordingPopen(proc)
    run = StubRun(exc=subprocess.TimeoutExpired(cmd="spd-say", timeout=2))
    engine = SpdSayEngine(binary="spd-say", popen=popen, run=run)

    def speak_thread() -> None:
        engine.speak("hello")

    thread = threading.Thread(target=speak_thread)
    thread.start()
    popen.started.wait(5.0)

    engine.cancel()

    assert proc.terminated is True
    thread.join(5.0)
    assert not thread.is_alive()


def test_should_terminate_and_not_raise_when_spd_say_binary_is_missing_for_cancel() -> None:
    proc = FakeProc(finished=False)
    popen = RecordingPopen(proc)
    run = StubRun(exc=FileNotFoundError("spd-say not found"))
    engine = SpdSayEngine(binary="spd-say", popen=popen, run=run)

    def speak_thread() -> None:
        engine.speak("hello")

    thread = threading.Thread(target=speak_thread)
    thread.start()
    popen.started.wait(5.0)

    engine.cancel()

    assert proc.terminated is True
    thread.join(5.0)
    assert not thread.is_alive()


def test_should_terminate_process_started_after_cancel_when_cancelled_during_spawn() -> None:
    proc = FakeProc(finished=False)
    popen = BlockingPopen(proc)
    run = StubRun()
    engine = SpdSayEngine(binary="spd-say", popen=popen, run=run)

    def speak_thread() -> None:
        engine.speak("hello")

    thread = threading.Thread(target=speak_thread)
    thread.start()
    popen.spawning.wait(5.0)

    engine.cancel()

    popen.release.set()
    thread.join(5.0)
    assert not thread.is_alive()
    assert proc.terminated is True


def test_should_speak_normally_when_cancel_was_called_while_idle() -> None:
    proc = FakeProc(finished=True)
    popen = RecordingPopen(proc)
    run = StubRun()
    engine = SpdSayEngine(binary="spd-say", popen=popen, run=run)

    engine.cancel()

    engine.speak("hi")

    assert len(popen.calls) == 1
    assert proc.terminated is False


def test_should_be_noop_when_cancel_called_after_speak_finished() -> None:
    proc = FakeProc(finished=True)
    popen = RecordingPopen(proc)
    run = StubRun()
    engine = SpdSayEngine(binary="spd-say", popen=popen, run=run)

    engine.speak("hello")

    engine.cancel()

    assert run.calls == []
    assert proc.terminated is False
