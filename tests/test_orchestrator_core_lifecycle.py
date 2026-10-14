"""Tests for the Orchestrator's failure, stop and shutdown paths."""

import asyncio
import os
import signal
import threading
from pathlib import Path

import pytest

from jarvis.brain import BrainUnavailable
from jarvis.orchestrator.timing import Timing
from jarvis.stt import SttUnavailable
from tests.core_rig import CoreRig
from tests.listener_rig import seg
from tests.orchestrator_rig import until

CLOSES = ["brain.close", "desktop.close", "speaker.close", "transcriber.close", "service.close"]


def no_capture_thread() -> bool:
    return not [t for t in threading.enumerate() if t.name == "jarvis-capture"]


def test_should_cancel_the_running_turn_and_record_it_when_the_user_says_stop(
    tmp_path: Path,
) -> None:
    async def scenario() -> CoreRig:
        rig = CoreRig(tmp_path, ["Jarvis, do a long thing", "Jarvis, stop"])
        assert rig.brain is not None
        rig.brain.release = asyncio.Event()  # never set: the turn only ends by cancellation
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await asyncio.wait_for(rig.brain.entered.wait(), 5)
            rig.feed.push(seg())
            await until(lambda: len(rig.records()) == 1)
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        return rig

    rig = asyncio.run(scenario())

    [record] = rig.records()
    assert record["drop_reason"] == "cancelled"
    assert rig.speaker.earcons == ["done"]
    assert rig.speaker.said == []


@pytest.mark.parametrize("trigger", ["request_stop", "sigint", "sigterm", "sighup"])
def test_should_close_every_child_when_asked_to_stop_mid_run(tmp_path: Path, trigger: str) -> None:
    async def scenario() -> CoreRig:
        rig = CoreRig(tmp_path, [])
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            await until(lambda: rig.states == ["idle"])
            if trigger == "request_stop":
                rig.orchestrator.request_stop()
            else:
                sig = {"sigint": "SIGINT", "sigterm": "SIGTERM", "sighup": "SIGHUP"}[trigger]
                os.kill(os.getpid(), getattr(signal, sig))
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        return rig

    rig = asyncio.run(scenario())

    assert rig.events[-5:] == CLOSES
    assert no_capture_thread()


def test_should_raise_the_source_error_after_closing_everything(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, [])
    rig.feed.fail(RuntimeError("mic gone"))

    with pytest.raises(RuntimeError, match="mic gone"):
        asyncio.run(asyncio.wait_for(rig.orchestrator.run(), 10))

    assert rig.events[-5:] == CLOSES
    assert no_capture_thread()


def test_should_close_the_children_when_the_transcriber_cannot_start(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, [])
    rig.transcriber.fail_start = SttUnavailable("no server", "install it")

    with pytest.raises(SttUnavailable):
        asyncio.run(asyncio.wait_for(rig.orchestrator.run(), 10))

    assert rig.events[-5:] == CLOSES


def test_should_keep_the_fast_path_working_when_the_brain_is_unavailable(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"])
    assert rig.brain is not None
    rig.brain.fail_start = BrainUnavailable("not logged in", ["Run claude and log in."])
    rig.feed.push(seg())
    rig.feed.end()

    asyncio.run(asyncio.wait_for(rig.orchestrator.run(), 10))

    assert "error" in rig.states
    assert rig.speaker.said == ["Volume 40 percent."]


def test_should_reset_the_brain_after_a_quiet_period_following_a_turn(tmp_path: Path) -> None:
    async def scenario() -> CoreRig:
        rig = CoreRig(
            tmp_path,
            ["Jarvis, what's the plan?"],
            timing=Timing(deaf_tail_s=0.0, inactivity_reset_s=0.05),
        )
        assert rig.brain is not None
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await asyncio.wait_for(rig.brain.reset_called.wait(), 5)
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        return rig

    rig = asyncio.run(scenario())

    assert rig.events.count("brain.reset") == 1


def test_should_purge_old_activity_files_when_it_starts(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, [])
    rig.activity_dir.mkdir(parents=True)
    old = rig.activity_dir / "2020-01-01.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    rig.feed.end()

    asyncio.run(asyncio.wait_for(rig.orchestrator.run(), 10))

    assert not old.exists()


def test_should_let_an_in_flight_transcription_finish_before_closing_the_transcriber(
    tmp_path: Path,
) -> None:
    async def scenario() -> CoreRig:
        rig = CoreRig(tmp_path, ["Jarvis, open it"])
        gate = threading.Event()
        rig.transcriber.gate = gate
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await until(lambda: "transcribe.start" in rig.events)
            rig.orchestrator.request_stop()
            await asyncio.sleep(0.05)  # shutdown is now waiting on the blocked thread
            assert "transcriber.close" not in rig.events
            gate.set()
            await asyncio.wait_for(run, 10)
        finally:
            gate.set()
            run.cancel()
        return rig

    rig = asyncio.run(scenario())

    assert rig.events.index("transcribe.end") < rig.events.index("transcriber.close")
    assert rig.events.count("transcriber.start") == 1


def test_should_not_reset_the_brain_while_a_newer_turn_is_still_running(tmp_path: Path) -> None:
    async def scenario() -> None:
        timing = Timing(deaf_tail_s=0.0, inactivity_reset_s=0.15)
        rig = CoreRig(tmp_path, ["Jarvis, first thing", "Jarvis, second thing"], timing=timing)
        assert rig.brain is not None
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await until(lambda: len(rig.records()) == 1 and rig.states[-1] == "idle")
            rig.brain.release = asyncio.Event()  # the second turn will run long
            rig.feed.push(seg())
            await until(lambda: rig.brain is not None and len(rig.brain.envelopes) == 2)
            await asyncio.sleep(0.4)  # longer than the inactivity period, measured from turn one
            assert not rig.brain.reset_called.is_set()
            rig.brain.release.set()
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()

    asyncio.run(scenario())
