import asyncio
import contextlib

from jarvis.orchestrator.windows import Windows


async def noop() -> None:
    return None


def test_should_be_none_when_fresh() -> None:
    windows = Windows()
    assert windows.kind is None


def test_should_set_listen_when_open_listen() -> None:
    async def scenario() -> None:
        windows = Windows()
        windows.open_listen(5, noop)
        assert windows.kind == "listen"

    asyncio.run(scenario())


def test_should_take_listen_when_open() -> None:
    async def scenario() -> None:
        windows = Windows()
        windows.open_listen(5, noop)
        assert windows.take_listen() is True
        assert windows.kind is None

    asyncio.run(scenario())


def test_should_not_take_listen_when_already_taken() -> None:
    async def scenario() -> None:
        windows = Windows()
        windows.open_listen(5, noop)
        windows.take_listen()
        assert windows.take_listen() is False

    asyncio.run(scenario())


def test_should_not_fire_callback_when_listen_taken_immediately() -> None:
    async def scenario() -> None:
        windows = Windows()
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        windows.open_listen(0.02, on_timeout)
        assert windows.take_listen() is True
        await asyncio.sleep(0.1)
        assert not fired.is_set()

    asyncio.run(scenario())


def test_should_fire_callback_when_listen_times_out() -> None:
    async def scenario() -> None:
        windows = Windows()
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        windows.open_listen(0.02, on_timeout)
        await asyncio.wait_for(fired.wait(), 2)
        assert windows.kind is None

    asyncio.run(scenario())


def test_should_not_take_listen_when_no_window() -> None:
    windows = Windows()
    assert windows.take_listen() is False


def test_should_not_take_listen_when_reply_open() -> None:
    async def scenario() -> None:
        windows = Windows()
        task = asyncio.create_task(windows.ask(5))
        await asyncio.sleep(0)
        assert windows.take_listen() is False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_should_not_offer_answer_when_no_window() -> None:
    windows = Windows()
    assert windows.offer_answer("hello") is False


def test_should_not_offer_answer_when_listen_open() -> None:
    async def scenario() -> None:
        windows = Windows()
        windows.open_listen(5, noop)
        assert windows.offer_answer("hello") is False

    asyncio.run(scenario())


def test_should_return_answer_when_ask_offered() -> None:
    async def scenario() -> None:
        windows = Windows()
        task = asyncio.create_task(windows.ask(5))
        await asyncio.sleep(0)
        assert windows.kind == "reply"
        assert windows.offer_answer("the second one") is True
        result = await task
        assert result == "the second one"
        assert windows.kind is None
        assert windows.offer_answer("again") is False

    asyncio.run(scenario())


def test_should_return_timeout_when_ask_expires() -> None:
    async def scenario() -> None:
        windows = Windows()
        result = await windows.ask(0.02)
        assert result == "timeout"
        assert windows.kind is None

    asyncio.run(scenario())


def test_should_return_timeout_when_close_while_ask_pending() -> None:
    async def scenario() -> None:
        windows = Windows()
        task = asyncio.create_task(windows.ask(5))
        await asyncio.sleep(0)
        windows.close()
        result = await task
        assert result == "timeout"

    asyncio.run(scenario())


def test_should_not_fire_callback_when_close_cancels_listen() -> None:
    async def scenario() -> None:
        windows = Windows()
        fired = asyncio.Event()

        async def on_timeout() -> None:
            fired.set()

        windows.open_listen(0.02, on_timeout)
        windows.close()
        await asyncio.sleep(0.1)
        assert not fired.is_set()

    asyncio.run(scenario())


def test_should_return_timeout_when_listen_replaces_ask() -> None:
    async def scenario() -> None:
        windows = Windows()
        task = asyncio.create_task(windows.ask(5))
        await asyncio.sleep(0)
        windows.open_listen(5, noop)
        result = await task
        assert result == "timeout"
        assert windows.kind == "listen"
        windows.close()

    asyncio.run(scenario())


def test_should_leave_kind_none_when_ask_task_cancelled() -> None:
    async def scenario() -> None:
        windows = Windows()
        task = asyncio.create_task(windows.ask(5))
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert windows.kind is None

    asyncio.run(scenario())
