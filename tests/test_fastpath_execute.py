"""Tests for jarvis.fastpath.executor: flow, gate ordering and denial."""

from collections.abc import Callable
from datetime import datetime

import pytest

from jarvis import policy
from jarvis.contract import validate_response
from jarvis.fastpath.intents import (
    CloseApp,
    Intent,
    Mute,
    OpenApp,
    TellDate,
    TellTime,
    VolumeSet,
    VolumeStep,
)
from tests.fastpath_fakes import (
    FakeDesktop,
    allow_gate,
    at,
    error_of,
    make_gate,
    run,
)


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.mark.parametrize(
    "intent, clock, spoken, tool",
    [
        (OpenApp("Calculator"), None, "Opening Calculator.", "desktop.open_app"),
        (CloseApp("Calculator"), None, "Closed Calculator.", "desktop.close_app"),
        (TellTime(), at(2026, 10, 7, 15, 42), "It's 3:42 PM.", "clock.time"),
        (TellDate(), at(2026, 10, 7, 12, 0), "It's Wednesday, 7 October.", "clock.date"),
        (VolumeSet(40), None, "Volume 40 percent.", "desktop.volume_set"),
        (VolumeStep(10), None, "Volume 50 percent.", "desktop.volume_step"),
        (Mute(True), None, "Muted.", "desktop.mute"),
        (Mute(False), None, "Unmuted.", "desktop.mute"),
    ],
)
def test_should_return_success_when_intent_allowed(
    events: list[str],
    intent: Intent,
    clock: Callable[[], datetime] | None,
    spoken: str,
    tool: str,
) -> None:
    desktop = FakeDesktop(events)
    response = run(intent, desktop, "balanced", clock=clock, gate=allow_gate(events))
    assert response.status == "success"
    assert response.spoken == spoken
    assert len(response.actions_taken) == 1
    assert response.actions_taken[0].tool == tool
    assert validate_response(response.model_dump()).spoken == spoken


def test_should_call_gate_before_desktop_when_opening_app(events: list[str]) -> None:
    desktop = FakeDesktop(events)
    run(OpenApp("Calculator"), desktop, "balanced", gate=allow_gate(events))
    assert events == ["gate", "desktop.open_app"]


@pytest.mark.parametrize("decision", [policy.Decision(False, "no"), None])
def test_should_return_blocked_when_gate_denies_or_raises(
    events: list[str], decision: policy.Decision | None
) -> None:
    desktop = FakeDesktop(events)
    response = run(OpenApp("Calculator"), desktop, "balanced", gate=make_gate(events, decision))
    assert response.status == "failed"
    assert error_of(response).code == "BLOCKED_BY_POLICY"
    assert error_of(response).remedy
    assert response.actions_taken == []
    assert validate_response(response.model_dump()).spoken == response.spoken
    assert events == ["gate"]


def test_should_allow_tools_in_balanced_or_t0_when_using_real_gate(events: list[str]) -> None:
    desktop = FakeDesktop(events)
    response = run(OpenApp("Calculator"), desktop, "balanced")
    assert response.status == "success"
    assert response.spoken == "Opening Calculator."
    desktop = FakeDesktop(events)
    response = run(TellTime(), desktop, "safe", clock=at(2026, 10, 7, 15, 42))
    assert response.status == "success"
    assert response.spoken == "It's 3:42 PM."
