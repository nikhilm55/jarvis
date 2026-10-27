import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.config import HudSettings, Settings
from jarvis.orchestrator.hud import HudEvent, HudSink
from tests.core_rig import CoreRig
from tests.listener_rig import seg
from tests.test_cli_run import Hook


class FakeHud:
    """Stands in for `running_hud` and records how it was called."""

    def __init__(self) -> None:
        self.events: list[HudEvent] = []
        self.calls: list[tuple[HudSettings, bool]] = []

    def __call__(
        self,
        hud: HudSettings,
        *,
        enabled: bool = True,
        answers: object = None,
        on_stop: Callable[[], Awaitable[None]] | None = None,
    ) -> AbstractAsyncContextManager[HudSink | None]:
        self.calls.append((hud, enabled))
        self.answers = answers
        self.on_stop = on_stop
        return self._cm(enabled)

    @contextlib.asynccontextmanager
    async def _cm(self, enabled: bool) -> AsyncIterator[HudSink | None]:
        if not enabled:
            yield None
            return
        yield self._sink

    async def _sink(self, event: HudEvent) -> None:
        self.events.append(event)


def test_should_disable_hud_and_skip_events_when_no_hud_flag_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"], with_brain=False)
    rig.feed.push(seg())
    rig.feed.end()
    hook = Hook(rig.parts)
    fake = FakeHud()
    monkeypatch.setattr(cli, "build_components", hook)
    monkeypatch.setattr(cli, "running_hud", fake)
    code = cli.main(
        [
            "run",
            "--source",
            str(tmp_path / "meeting.wav"),
            "--no-brain",
            "--no-hud",
        ]
    )
    assert code == 0
    assert fake.calls == [(Settings().hud, False)]
    assert fake.answers is rig.parts.answers  # the card's answers reach the turn's confirmer
    assert fake.events == []
    out = capsys.readouterr().out
    assert "[speaking] Volume 40 percent." in out


def test_should_enable_hud_and_forward_events_when_hud_is_default_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"], with_brain=False)
    rig.feed.push(seg())
    rig.feed.end()
    hook = Hook(rig.parts)
    fake = FakeHud()
    monkeypatch.setattr(cli, "build_components", hook)
    monkeypatch.setattr(cli, "running_hud", fake)
    code = cli.main(
        [
            "run",
            "--source",
            str(tmp_path / "meeting.wav"),
            "--no-brain",
        ]
    )
    assert code == 0
    assert fake.calls == [(Settings().hud, True)]
    states = [(e.state, e.text) for e in fake.events]
    assert ("speaking", "Volume 40 percent.") in states
    out = capsys.readouterr().out
    assert "[speaking] Volume 40 percent." in out


def test_should_call_first_sink_only_when_second_is_none() -> None:
    calls: list[str] = []

    async def first(event: HudEvent) -> None:
        calls.append("first")

    sink = cli._tee(first, None)

    async def send() -> None:
        await sink(HudEvent(state="speaking", text="x"))

    asyncio.run(send())
    assert calls == ["first"]


def test_should_call_both_sinks_in_order_when_second_is_present() -> None:
    calls: list[str] = []

    async def first(event: HudEvent) -> None:
        calls.append("first")

    async def second(event: HudEvent) -> None:
        calls.append("second")

    sink = cli._tee(first, second)

    async def send() -> None:
        await sink(HudEvent(state="speaking", text="x"))

    asyncio.run(send())
    assert calls == ["first", "second"]
