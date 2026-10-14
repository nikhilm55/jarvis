"""Tests for src/jarvis/tts/engines.py (SpdSayEngine and default_engine)."""

import subprocess
import threading
from typing import Any

import pytest

from jarvis.config import TtsSettings
from jarvis.tts.engines import AudioEngine, DirectEngine, SpdSayEngine, default_engine


class FakeProc:
    """A fake subprocess.Popen result that blocks on a threading.Event."""

    def __init__(self, returncode: int = 0, finished: bool = False) -> None:
        self._done = threading.Event()
        self._returncode = returncode
        self.terminated = False
        if finished:
            self._done.set()

    def wait(self, timeout: float | None = None) -> int:
        self._done.wait(timeout=5.0)
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._done.set()

    def poll(self) -> int | None:
        return self._returncode if self._done.is_set() else None


class FakePopen:
    """Callable class that records argv lists and kwargs and returns a FakeProc."""

    def __init__(self, proc: FakeProc | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._proc = proc
        self._error = error
        self.started = threading.Event()

    def __call__(self, argv: list[str], **kwargs: Any) -> FakeProc:
        self.calls.append((list(argv), dict(kwargs)))
        self.started.set()
        if self._error is not None:
            raise self._error
        if self._proc is not None:
            return self._proc
        return FakeProc()


def make_fake_run() -> tuple[list[tuple[list[str], dict[str, Any]]], Any]:
    """Create a recording fake_run that returns CompletedProcess(argv, 0)."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        calls.append((list(argv), dict(kwargs)))
        return subprocess.CompletedProcess(argv, 0)

    return calls, fake_run


def test_should_run_popen_with_expected_argv_when_speaking_plain_text() -> None:
    proc = FakeProc(finished=True)
    fake_popen = FakePopen(proc=proc)
    engine = SpdSayEngine(popen=fake_popen)

    engine.speak("Hello there.")

    assert len(fake_popen.calls) == 1
    argv, kwargs = fake_popen.calls[0]
    assert argv == ["spd-say", "-w", "--", "Hello there."]
    assert not kwargs.get("shell", False)


def test_should_keep_text_after_separator_when_text_starts_with_dash() -> None:
    proc = FakeProc(finished=True)
    fake_popen = FakePopen(proc=proc)
    engine = SpdSayEngine(popen=fake_popen)

    engine.speak("-rf rm")

    argv, _ = fake_popen.calls[0]
    assert argv == ["spd-say", "-w", "--", "-rf rm"]


def test_should_use_custom_binary_path_when_configured() -> None:
    proc = FakeProc(finished=True)
    fake_popen = FakePopen(proc=proc)
    engine = SpdSayEngine(binary="/opt/spd/spd-say", popen=fake_popen)

    engine.speak("hi")

    argv, _ = fake_popen.calls[0]
    assert argv[0] == "/opt/spd/spd-say"


def test_should_cancel_running_process_when_cancel_called_during_speak() -> None:
    proc = FakeProc()
    fake_popen = FakePopen(proc=proc)
    run_calls, fake_run = make_fake_run()
    engine = SpdSayEngine(popen=fake_popen, run=fake_run)

    def _speak() -> None:
        engine.speak("long text")

    thread = threading.Thread(target=_speak)
    thread.start()

    assert fake_popen.started.wait(5.0)
    assert thread.is_alive()

    engine.cancel()

    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert proc.terminated
    assert len(run_calls) == 1
    argv, _ = run_calls[0]
    assert argv == ["spd-say", "-C"]


def test_should_clear_running_process_when_speak_completes() -> None:
    proc = FakeProc(finished=True)
    fake_popen = FakePopen(proc=proc)
    run_calls, fake_run = make_fake_run()
    engine = SpdSayEngine(popen=fake_popen, run=fake_run)

    engine.speak("hello")

    engine.cancel()

    assert not proc.terminated
    assert len(run_calls) == 0


def test_should_not_raise_or_terminate_when_cancel_called_with_nothing_running() -> None:
    proc = FakeProc(finished=True)
    fake_popen = FakePopen(proc=proc)
    run_calls, fake_run = make_fake_run()
    engine = SpdSayEngine(popen=fake_popen, run=fake_run)

    engine.cancel()

    assert not proc.terminated
    assert len(run_calls) == 0


def test_should_be_harmless_when_cancel_called_twice() -> None:
    proc = FakeProc(finished=True)
    fake_popen = FakePopen(proc=proc)
    run_calls, fake_run = make_fake_run()
    engine = SpdSayEngine(popen=fake_popen, run=fake_run)

    engine.cancel()
    engine.cancel()

    assert not proc.terminated
    assert len(run_calls) == 0


def test_should_propagate_file_not_found_error_when_popen_raises() -> None:
    fake_popen = FakePopen(error=FileNotFoundError("spd-say not found"))
    engine = SpdSayEngine(popen=fake_popen)

    with pytest.raises(FileNotFoundError):
        engine.speak("hello")


def test_should_be_direct_engine_not_audio_engine_when_instantiated() -> None:
    engine = SpdSayEngine()

    assert isinstance(engine, DirectEngine)
    assert not isinstance(engine, AudioEngine)


def test_should_return_spd_say_engine_when_default_engine_with_spd_say_setting() -> None:
    settings = TtsSettings(engine="spd-say")

    engine = default_engine(settings)

    assert isinstance(engine, SpdSayEngine)
