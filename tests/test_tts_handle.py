"""Tests for jarvis.tts.handle.SpeechHandle."""

import threading

import pytest

from jarvis.tts.handle import SpeechHandle


class _Clock:
    """A tiny settable clock: `now` attribute, `__call__` returns it."""

    def __init__(self, value: float = 0.0) -> None:
        self.now = value

    def __call__(self) -> float:
        return self.now


def _make_handle(clock: _Clock | None = None, text: str = "hello") -> SpeechHandle:
    return SpeechHandle(text, clock if clock is not None else _Clock())


def test_should_be_speaking_when_fresh() -> None:
    handle = _make_handle()
    assert handle.is_speaking is True


def test_should_not_be_failed_when_fresh() -> None:
    handle = _make_handle()
    assert handle.failed is False


def test_should_not_be_cancelled_when_fresh() -> None:
    handle = _make_handle()
    assert handle.cancelled is False


def test_should_have_none_first_audio_when_fresh() -> None:
    handle = _make_handle()
    assert handle.first_audio_s is None


def test_should_wait_return_false_when_fresh_with_zero_timeout() -> None:
    handle = _make_handle()
    assert handle.wait(0) is False


def test_should_record_first_audio_when_noted_once() -> None:
    clock = _Clock(1.0)
    handle = _make_handle(clock)
    clock.now = 3.5
    handle._note_first_audio()
    assert handle.first_audio_s == pytest.approx(2.5)


def test_should_not_update_first_audio_when_noted_twice() -> None:
    clock = _Clock(1.0)
    handle = _make_handle(clock)
    clock.now = 3.5
    handle._note_first_audio()
    clock.now = 10.0
    handle._note_first_audio()
    assert handle.first_audio_s == pytest.approx(2.5)


def test_should_stop_speaking_when_cancelled() -> None:
    handle = _make_handle()
    handle.cancel()
    assert handle.is_speaking is False


def test_should_wait_return_true_when_cancelled_with_zero_timeout() -> None:
    handle = _make_handle()
    handle.cancel()
    assert handle.wait(0) is True


def test_should_be_cancelled_when_cancelled() -> None:
    handle = _make_handle()
    handle.cancel()
    assert handle.cancelled is True


def test_should_fire_callback_exactly_once_when_cancelled_twice() -> None:
    handle = _make_handle()
    calls: list[None] = []
    handle._register_cancel(lambda: calls.append(None))
    handle.cancel()
    handle.cancel()
    assert len(calls) == 1


def test_should_run_callback_immediately_when_registered_after_cancel() -> None:
    handle = _make_handle()
    handle.cancel()
    ran = threading.Event()
    handle._register_cancel(ran.set)
    assert ran.is_set()


def test_should_not_call_callbacks_when_cleared_then_cancelled() -> None:
    handle = _make_handle()
    ran = threading.Event()
    handle._register_cancel(ran.set)
    handle._clear_cancel()
    handle.cancel()
    assert ran.is_set() is False


def test_should_end_without_failed_when_finished() -> None:
    handle = _make_handle()
    handle._finish()
    assert handle.is_speaking is False
    assert handle.failed is False


def test_should_end_with_failed_when_failed() -> None:
    handle = _make_handle()
    handle._fail()
    assert handle.is_speaking is False
    assert handle.failed is True


def test_should_wait_return_false_when_pending_with_small_timeout() -> None:
    handle = _make_handle()
    assert handle.wait(0.01) is False


def test_should_wait_return_true_when_finished_from_other_thread() -> None:
    handle = _make_handle()
    done = threading.Event()

    def finisher() -> None:
        handle._finish()
        done.set()

    t = threading.Thread(target=finisher)
    t.start()
    assert handle.wait(5.0) is True
    t.join(timeout=5.0)
    assert t.is_alive() is False
