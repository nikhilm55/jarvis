"""Tests for jarvis.brain.clock.TurnClock."""

import asyncio

from jarvis.brain.clock import TurnClock


def test_should_pause_and_resume_scope_when_clock_attached() -> None:
    async def main() -> None:
        clock = TurnClock()
        async with asyncio.timeout(10) as scope:
            clock.attach(scope)
            before = scope.when()
            clock.pause()
            assert scope.when() is None
            clock.resume()
            after = scope.when()
            assert before is not None
            assert after is not None
            assert abs(after - before) < 1.0

    asyncio.run(main())


def test_should_only_resume_outer_when_nested_pause() -> None:
    async def main() -> None:
        clock = TurnClock()
        async with asyncio.timeout(10) as scope:
            clock.attach(scope)
            clock.pause()
            clock.pause()
            clock.resume()
            assert scope.when() is None
            clock.resume()
            assert scope.when() is not None

    asyncio.run(main())


def test_should_noop_when_resume_without_pause() -> None:
    async def main() -> None:
        clock = TurnClock()
        async with asyncio.timeout(10) as scope:
            clock.attach(scope)
            before = scope.when()
            clock.resume()
            after = scope.when()
            assert before is not None
            assert after is not None
            assert abs(after - before) < 1.0

    asyncio.run(main())


def test_should_not_raise_when_pause_resume_without_scope() -> None:
    clock = TurnClock()
    clock.pause()
    clock.resume()


def test_should_not_raise_when_pause_and_resume_straddle_the_scope_exit() -> None:
    async def main() -> None:
        clock = TurnClock()
        async with asyncio.timeout(10) as scope:
            clock.attach(scope)
            clock.pause()
        clock.resume()  # the turn is over; a late ask finishing must not crash
        clock.pause()
        clock.resume()

    asyncio.run(main())
