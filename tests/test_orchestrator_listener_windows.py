"""Tests for the Listener windows: bare "Jarvis" listen window and the reply window."""

import asyncio
import contextlib
from pathlib import Path

from jarvis.orchestrator.listener import NOT_UNDERSTOOD, WAKE_PROMPT
from jarvis.orchestrator.timing import Timing
from tests.listener_rig import make_listener_rig, seg
from tests.orchestrator_rig import until


def test_should_play_wake_earcon_and_open_listen_window_when_bare_jarvis(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis"])
        await rig.listener.handle(seg())
        assert rig.speaker.earcons == ["wake"]
        assert rig.states == ["transcript", "listening"]
        assert rig.windows.kind == "listen"
        assert rig.submitted == []
        rig.windows.close()

    asyncio.run(scenario())


def test_should_strip_wake_word_when_next_segment_is_command(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis", "open the calculator"])
        await rig.listener.handle(seg())
        await rig.listener.handle(seg(score=0.0, silence_ms=0))
        assert rig.submitted[0].text == "open the calculator"
        assert rig.transcriber.prompts == [WAKE_PROMPT, None]
        assert rig.windows.kind is None

    asyncio.run(scenario())


def test_should_strip_wake_word_inside_window_when_command_repeats_wake_word(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis", "Jarvis, open the calculator"])
        await rig.listener.handle(seg())
        await rig.listener.handle(seg(score=0.0, silence_ms=0))
        assert rig.submitted[0].text == "open the calculator"
        assert rig.submitted[0].raw == "Jarvis, open the calculator"

    asyncio.run(scenario())


def test_should_keep_listen_window_open_when_segment_is_tainted(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis"])
        await rig.listener.handle(seg())
        await rig.listener.handle(seg(tainted=True))
        assert rig.windows.kind == "listen"
        assert len(rig.transcriber.prompts) == 1
        rig.windows.close()

    asyncio.run(scenario())


def test_should_speak_not_understood_when_transcript_is_empty_in_listen_window(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis", ""])
        await rig.listener.handle(seg())
        await rig.listener.handle(seg(score=0.0, silence_ms=0))
        assert rig.speaker.said == [NOT_UNDERSTOOD]
        assert rig.submitted == []

    asyncio.run(scenario())


def test_should_close_listen_window_when_it_times_out(tmp_path: Path) -> None:
    async def scenario() -> None:
        timing = Timing(listen_window_s=0.02, deaf_tail_s=0.0)
        rig = make_listener_rig(tmp_path, ["Jarvis"], timing)
        await rig.listener.handle(seg())
        await until(lambda: rig.windows.kind is None)
        assert "idle" in rig.states
        await rig.listener.handle(seg(score=0.0))
        assert len(rig.transcriber.prompts) == 1
        assert rig.submitted == []

    asyncio.run(scenario())


def test_should_deliver_raw_text_when_reply_window_is_open(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis, yes please"])
        task = asyncio.create_task(rig.windows.ask(5))
        try:
            await asyncio.sleep(0)
            await rig.listener.handle(seg(score=0.0, silence_ms=0))
            assert await task == "Jarvis, yes please"
            assert rig.transcriber.prompts == [None]
            assert rig.submitted == []
            assert "transcript" in rig.states
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_should_keep_reply_window_open_when_transcript_is_empty(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, [""])
        task = asyncio.create_task(rig.windows.ask(5))
        try:
            await asyncio.sleep(0)
            await rig.listener.handle(seg(score=0.0, silence_ms=0))
            assert rig.speaker.said == [NOT_UNDERSTOOD]
            assert rig.windows.kind == "reply"
            rig.windows.close()
            assert await task == "timeout"
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_should_stop_and_not_deliver_when_reply_window_text_is_stop(tmp_path: Path) -> None:
    async def scenario() -> None:
        rig = make_listener_rig(tmp_path, ["Jarvis, stop"])
        task = asyncio.create_task(rig.windows.ask(5))
        try:
            await asyncio.sleep(0)
            await rig.listener.handle(seg(score=0.0, silence_ms=0))
            assert rig.stops == 1
            assert rig.windows.kind == "reply"
            rig.windows.close()
            assert await task == "timeout"
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())
