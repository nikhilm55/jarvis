"""FR-CON-14: the access badge, 'Reading Teams…', while a tool touches personal data."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest

from jarvis.hud.page import read_page
from jarvis.orchestrator.access import AccessBadge, badge_text
from jarvis.orchestrator.hud import HudEvent
from jarvis.policy import Tier
from tests.gated_rig import Consent, Impl, clean_state, dispatch, tool  # noqa: F401


@pytest.mark.parametrize(
    ("scopes", "text"),
    [
        (("messages.teams:read",), "Reading Teams…"),
        (("messages.teams:read", "messages.teams:write"), "Using Teams…"),
        (("calendar.google:read", "messages.teams:read"), "Reading Google and Teams…"),
        (("screen:read",), "Reading Screen…"),
    ],
)
def test_should_name_the_sources_being_touched(scopes: tuple[str, ...], text: str) -> None:
    assert badge_text(scopes) == text


def test_should_show_the_badge_during_the_tool_and_take_it_down_after() -> None:
    events: list[HudEvent] = []

    async def hud(event: HudEvent) -> None:
        events.append(event)

    badge = AccessBadge(hud)

    async def scenario() -> None:
        async with (
            badge.touching(("messages.teams:read",)),
            badge.touching(("calendar.google:read",)),
        ):
            pass
        with pytest.raises(RuntimeError):
            async with badge.touching(("screen:read",)):
                raise RuntimeError("tool failed")

    asyncio.run(scenario())
    texts = [(e.text, e.extra.get("closed", False)) for e in events]
    assert texts == [
        ("Reading Teams…", False),
        ("Reading Google…", False),
        ("", True),  # down once, after the outer tool
        ("Reading Screen…", False),
        ("", True),  # down even when the tool fails
    ]


class Probe:
    def __init__(self) -> None:
        self.log: list[object] = []

    @contextlib.asynccontextmanager
    async def touching(self, scopes: tuple[str, ...]) -> AsyncIterator[None]:
        self.log.append(scopes)
        yield
        self.log.append("down")


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [(("messages.teams:read",), [("messages.teams:read",), "down"]), ((), [])],
)
def test_should_wrap_only_a_tool_with_scopes(
    scopes: tuple[str, ...], expected: list[object]
) -> None:
    tool("t.read", Tier.T0, scopes=scopes)
    probe = Probe()
    _, _, impl = dispatch(
        "t.read", {}, mode="yolo", consent=Consent("granted"), touching=probe.touching
    )
    assert len(impl.calls) == 1 and probe.log == expected


def test_should_show_the_badge_beside_the_pill_on_the_page() -> None:
    page = read_page()
    assert 'id="access"' in page
    assert "if (ev.state === 'access_badge') { showAccess(ev); return; }" in page
