import asyncio
import time
from pathlib import Path

from jarvis.orchestrator.timing import Timing
from tests.core_rig import CoreRig
from tests.listener_rig import make_listener_rig, seg
from tests.orchestrator_rig import until


def test_should_keep_listen_window_open_when_speech_started_inside_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(
            tmp_path,
            ["Jarvis", "what is the plan"],
            timing=Timing(listen_window_s=0.05, deaf_tail_s=0.0),
        )
        await rig.listener.handle(seg())
        assert rig.windows.kind == "listen"
        assert rig.windows.hold_if_open(time.monotonic())
        await asyncio.sleep(0.15)
        assert rig.windows.kind == "listen"
        await rig.listener.handle(seg(score=0.0, silence_ms=0))
        assert rig.submitted[0].text == "what is the plan"

    asyncio.run(scenario())


def test_should_keep_reply_window_open_when_speech_started_inside_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["the second one"])
        task = asyncio.create_task(rig.windows.ask(0.05))
        await asyncio.sleep(0)
        assert rig.windows.hold_if_open(time.monotonic())
        await asyncio.sleep(0.15)
        assert not task.done()
        await rig.listener.handle(seg(score=0.0, silence_ms=0))
        assert await task == "the second one"

    asyncio.run(scenario())


def test_should_release_hold_when_tainted_segment_arrives_in_listen_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(
            tmp_path,
            ["Jarvis"],
            timing=Timing(listen_window_s=0.05, deaf_tail_s=0.0),
        )
        await rig.listener.handle(seg())
        assert rig.windows.kind == "listen"
        assert rig.windows.hold_if_open(time.monotonic())
        await rig.listener.handle(seg(tainted=True))
        await until(lambda: rig.windows.kind is None)
        assert "idle" in rig.states

    asyncio.run(scenario())


def test_should_release_hold_when_empty_transcript_in_held_reply_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, [""])
        task = asyncio.create_task(rig.windows.ask(0.05))
        await asyncio.sleep(0)
        assert rig.windows.hold_if_open(time.monotonic())
        await rig.listener.handle(seg(score=0.0, silence_ms=0))
        assert await asyncio.wait_for(task, 2) == "timeout"

    asyncio.run(scenario())


def test_should_honour_speech_started_inside_window_end_to_end(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = CoreRig(
            tmp_path,
            ["Jarvis", "what is the plan"],
            timing=Timing(listen_window_s=0.1, deaf_tail_s=0.0),
        )
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await until(lambda: rig.windows.kind == "listen")
            rig.feed.start(time.monotonic())
            await asyncio.sleep(0.25)
            rig.feed.push(seg(score=0.0, silence_ms=0))
            rig.feed.end()
            await asyncio.wait_for(run, 10)
            assert rig.brain is not None
            assert [e.command for e in rig.brain.envelopes] == ["what is the plan"]
        finally:
            run.cancel()

    asyncio.run(scenario())
