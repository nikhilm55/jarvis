"""Tests for safe_sink and for the Orchestrator surviving a broken HUD."""

import asyncio
import logging
from pathlib import Path

import pytest

from jarvis.orchestrator.hud import HudEvent, safe_sink
from tests.core_rig import CoreRig
from tests.listener_rig import seg


def test_should_forward_event_when_sink_is_healthy() -> None:
    seen: list[HudEvent] = []

    async def sink(event: HudEvent) -> None:
        seen.append(event)

    async def scenario() -> None:
        await safe_sink(sink)(HudEvent("idle"))

    asyncio.run(scenario())
    assert seen == [HudEvent("idle")]


def test_should_swallow_the_failure_and_warn_once_without_the_event_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def sink(event: HudEvent) -> None:
        raise RuntimeError("hud down")

    caplog.set_level(logging.WARNING, logger="jarvis.hud")

    async def scenario() -> None:
        await safe_sink(sink)(HudEvent("reply", "secret words"))

    asyncio.run(scenario())

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "secret words" not in caplog.text


def test_should_propagate_cancellation_when_sink_cancels() -> None:
    async def sink(event: HudEvent) -> None:
        raise asyncio.CancelledError()

    async def scenario() -> None:
        await safe_sink(sink)(HudEvent("idle"))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scenario())


def test_should_keep_running_when_hud_always_raises(tmp_path: Path) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"], with_brain=False)
    rig.hud_fails = True
    rig.feed.push(seg())
    rig.feed.end()

    asyncio.run(asyncio.wait_for(rig.orchestrator.run(), 10))

    assert rig.speaker.said == ["Volume 40 percent."]
    assert rig.hud_events
