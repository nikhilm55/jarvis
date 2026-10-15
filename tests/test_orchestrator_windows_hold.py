"""Tests for Windows speech-start anchoring: hold_if_open and release."""

import asyncio
import time

from jarvis.orchestrator.windows import Windows


class FakeClock:
    def __init__(self) -> None:
        self.now: float = 0.0

    def __call__(self) -> float:
        return self.now


async def noop() -> None:
    return None


def test_should_accept_hold_before_deadline_and_refuse_after_when_window_open() -> None:
    async def scenario() -> None:
        w = Windows(FakeClock())
        w.open_listen(5, noop)
        assert w.hold_if_open(6.0) is False
        assert w.hold_if_open(4.9) is True
        assert w.hold_if_open(4.9) is False
        w.close()

    asyncio.run(scenario())


def test_should_refuse_hold_when_no_window_open() -> None:
    clock = FakeClock()
    w = Windows(clock)
    assert w.hold_if_open(0.0) is False


def test_should_not_time_out_when_listen_window_held() -> None:
    async def scenario() -> None:
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        w = Windows()
        w.open_listen(0.02, on_timeout)
        assert w.hold_if_open(time.monotonic())
        await asyncio.sleep(0.1)
        assert not fired.is_set()
        assert w.kind == "listen"
        assert w.take_listen() is True
        assert w.kind is None

    asyncio.run(scenario())


def test_should_expire_window_when_released_after_deadline() -> None:
    async def scenario() -> None:
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        w = Windows()
        w.open_listen(0.02, on_timeout)
        assert w.hold_if_open(time.monotonic())
        await asyncio.sleep(0.1)
        w.release()
        await asyncio.wait_for(fired.wait(), 2)
        assert w.kind is None

    asyncio.run(scenario())


def test_should_keep_waiting_when_released_with_time_left() -> None:
    async def scenario() -> None:
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        w = Windows()
        w.open_listen(0.3, on_timeout)
        assert w.hold_if_open(time.monotonic())
        w.release()
        await asyncio.sleep(0)
        assert not fired.is_set()
        await asyncio.wait_for(fired.wait(), 2)

    asyncio.run(scenario())


def test_should_not_time_out_and_still_take_answer_when_reply_window_held() -> None:
    async def scenario() -> None:
        w = Windows()
        task = asyncio.create_task(w.ask(0.02))
        await asyncio.sleep(0)
        assert w.hold_if_open(time.monotonic())
        await asyncio.sleep(0.1)
        assert not task.done()
        assert w.offer_answer("the second one") is True
        assert await task == "the second one"

    asyncio.run(scenario())


def test_should_time_out_when_released_reply_window_expires() -> None:
    async def scenario() -> None:
        w = Windows()
        task = asyncio.create_task(w.ask(0.02))
        await asyncio.sleep(0)
        assert w.hold_if_open(time.monotonic())
        await asyncio.sleep(0.1)
        w.release()
        assert await task is None

    asyncio.run(scenario())


def test_should_clear_hold_and_callback_when_close_on_held_window() -> None:
    async def scenario() -> None:
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        w = Windows()
        w.open_listen(0.02, on_timeout)
        assert w.hold_if_open(time.monotonic())
        w.close()
        assert w.kind is None
        w.release()
        assert w.kind is None
        await asyncio.sleep(0.1)
        assert not fired.is_set()

    asyncio.run(scenario())
