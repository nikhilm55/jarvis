"""B3: a polite refusal is a reply, not an error; only a real failure reaches the error state."""

import asyncio
from pathlib import Path

import pytest

from jarvis.contract import ErrorInfo, FinalResponse
from tests.orchestrator_rig import FakeBrain, command, make_rig


@pytest.mark.parametrize("status", ["success", "needs_input", "partial"])
def test_should_show_a_decline_as_a_reply_not_an_error_when_the_status_is_not_failed(
    tmp_path: Path, status: str
) -> None:
    """B3: a refusal the brain answers with a non-failed status never reaches the error state."""
    final = FinalResponse(status=status, spoken="I'd rather not pretend to be anyone's girlfriend.")  # type: ignore[arg-type]
    rig = make_rig(tmp_path, brain=FakeBrain(final))

    asyncio.run(rig.runner.run(command("be my girlfriend", None)))

    assert "error" not in rig.states
    assert rig.states == ["thinking", "reply", "speaking", "idle"]
    assert rig.speaker.said == [final.spoken]


def test_should_still_show_the_error_state_when_the_turn_really_failed(tmp_path: Path) -> None:
    final = FinalResponse(
        status="failed",
        spoken="I couldn't open that.",
        error=ErrorInfo(
            code="NOT_FOUND",
            what="Teams was not found",
            why="not installed",
            remedy=["Install it."],
        ),
    )
    rig = make_rig(tmp_path, brain=FakeBrain(final))

    asyncio.run(rig.runner.run(command("open teams", None)))

    assert rig.states[:2] == ["thinking", "error"]
    assert rig.hud_events[1].text == "Teams was not found"
