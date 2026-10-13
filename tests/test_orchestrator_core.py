"""Tests for jarvis.orchestrator.core: the whole loop on fakes, start to shutdown."""

import asyncio
import threading
from pathlib import Path

from tests.core_rig import CoreRig
from tests.listener_rig import seg
from tests.orchestrator_rig import until


async def run_to_end(rig: CoreRig) -> None:
    await asyncio.wait_for(rig.orchestrator.run(), 10)


def test_should_run_a_fast_path_turn_end_to_end(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"], with_brain=False)
    rig.feed.push(seg())
    rig.feed.end()

    asyncio.run(run_to_end(rig))

    assert rig.speaker.said == ["Volume 40 percent."]
    assert rig.desktop.events == ["desktop.volume_set"]
    [record] = rig.records()
    assert record["route"] == "fastpath"
    assert rig.states[-1] == "idle"


def test_should_run_a_brain_turn_end_to_end(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, what's on my calendar?"])
    assert rig.brain is not None
    rig.feed.push(seg())
    rig.feed.end()

    asyncio.run(run_to_end(rig))

    assert rig.speaker.said == ["Handled by the brain."]
    assert [e.command for e in rig.brain.envelopes] == ["what's on my calendar?"]
    [record] = rig.records()
    assert record["route"] == "brain"


def test_should_warm_every_child_before_it_listens(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, [])
    rig.feed.end()

    asyncio.run(run_to_end(rig))

    assert rig.events[0] == "service.start"
    assert set(rig.events[1:3]) == {"transcriber.start", "brain.start"}
    assert rig.states[0] == "idle"


def test_should_close_every_child_and_the_capture_thread_when_the_source_ends(
    tmp_path: Path,
) -> None:
    rig = CoreRig(tmp_path, [])
    rig.feed.end()

    asyncio.run(run_to_end(rig))

    assert rig.events[-5:] == [
        "brain.close",
        "desktop.close",
        "speaker.close",
        "transcriber.close",
        "service.close",
    ]
    assert rig.feed.closed.is_set()
    assert [t for t in threading.enumerate() if t.name == "jarvis-capture"] == []


def test_should_run_queued_commands_one_at_a_time_in_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = CoreRig(tmp_path, ["Jarvis, first thing", "Jarvis, second thing"])
        assert rig.brain is not None
        rig.brain.release = asyncio.Event()
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await asyncio.wait_for(rig.brain.entered.wait(), 5)
            rig.feed.push(seg())
            await until(lambda: rig.states.count("transcript") == 2)
            assert len(rig.brain.envelopes) == 1
            rig.brain.release.set()
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        assert [e.command for e in rig.brain.envelopes] == ["first thing", "second thing"]

    asyncio.run(scenario())
