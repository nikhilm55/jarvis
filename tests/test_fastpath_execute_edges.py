"""Tests for jarvis.fastpath.executor: policy modes, desktop errors and registration."""

import asyncio
import threading
from collections.abc import Mapping

import pytest

from jarvis import policy
from jarvis.contract import FinalResponse, validate_response
from jarvis.desktop.client import DesktopError
from jarvis.fastpath import FastPathDeclined, execute
from jarvis.fastpath.intents import (
    CloseApp,
    Intent,
    Mute,
    OpenApp,
    Stop,
    TellDate,
    TellTime,
    VolumeSet,
    VolumeStep,
)
from jarvis.policy import Mode
from tests.fastpath_fakes import FakeDesktop, allow_gate, error_of, run


@pytest.fixture
def events() -> list[str]:
    return []


def test_should_report_not_open_when_close_reports_zero_closed(events: list[str]) -> None:
    desktop = FakeDesktop(events, results={"close_app": {"app": "Calculator", "closed": 0}})
    response = run(CloseApp("Calculator"), desktop, "balanced", gate=allow_gate(events))
    assert response.status == "success"
    assert response.spoken == "Calculator isn't open."
    assert response.actions_taken == []
    assert events == ["gate", "desktop.close_app"]


@pytest.mark.parametrize(
    "intent, tool, args",
    [
        (OpenApp("Calculator"), "desktop.open_app", {"query": "Calculator"}),
        (CloseApp("Calculator"), "desktop.close_app", {"query": "Calculator"}),
        (TellTime(), "clock.time", {}),
        (TellDate(), "clock.date", {}),
        (VolumeSet(40), "desktop.volume_set", {"pct": 40}),
        (VolumeStep(10), "desktop.volume_step", {"delta": 10}),
        (Mute(True), "desktop.mute", {"on": True}),
    ],
)
def test_should_pass_exact_tool_args_to_gate_when_executing(
    events: list[str],
    intent: Intent,
    tool: str,
    args: Mapping[str, object],
) -> None:
    captured: list[tuple[str, Mapping[str, object], Mode]] = []

    def gate(t: str, a: Mapping[str, object], m: Mode) -> policy.Decision:
        captured.append((t, a, m))
        return policy.Decision(True, "ok")

    desktop = FakeDesktop(events)
    run(intent, desktop, "balanced", gate=gate)
    assert captured == [(tool, args, "balanced")]


def test_should_run_gate_in_worker_thread_when_executing(events: list[str]) -> None:
    gate_ids: list[int] = []

    def gate(tool: str, args: Mapping[str, object], mode: Mode) -> policy.Decision:
        gate_ids.append(threading.get_ident())
        return policy.Decision(True, "ok")

    async def capture() -> tuple[int, FinalResponse]:
        main_id = threading.get_ident()
        response = await execute(OpenApp("Calculator"), FakeDesktop(events), "balanced", gate=gate)
        return main_id, response

    main_id, response = asyncio.run(capture())
    assert response.status == "success"
    assert gate_ids and gate_ids[0] != main_id


@pytest.mark.parametrize("intent", [OpenApp("Calculator"), CloseApp("Calculator")])
def test_should_block_desktop_tools_in_safe_mode_when_using_real_gate(
    events: list[str], intent: Intent
) -> None:
    desktop = FakeDesktop(events)
    response = run(intent, desktop, "safe")
    assert response.status == "failed"
    assert error_of(response).code == "BLOCKED_BY_POLICY"
    assert "balanced" in error_of(response).remedy[0]
    assert events == []


def test_should_raise_value_error_when_intent_is_stop(events: list[str]) -> None:
    desktop = FakeDesktop(events)
    with pytest.raises(ValueError):
        run(Stop(), desktop, "balanced", gate=allow_gate(events))
    assert events == []


@pytest.mark.parametrize("code", ["NOT_FOUND", "AMBIGUOUS"])
@pytest.mark.parametrize("intent", [OpenApp("Calculator"), CloseApp("Calculator")])
def test_should_decline_when_desktop_reports_not_found_or_ambiguous(
    events: list[str], code: str, intent: Intent
) -> None:
    desktop = FakeDesktop(events, error=DesktopError(code, "msg"))
    with pytest.raises(FastPathDeclined) as exc:
        run(intent, desktop, "balanced", gate=allow_gate(events))
    assert code in str(exc.value)


@pytest.mark.parametrize(
    "intent, code, mapped",
    [
        (OpenApp("Calculator"), "TIMEOUT", "TIMEOUT"),
        (OpenApp("Calculator"), "INTERNAL", "INTERNAL"),
        (OpenApp("Calculator"), "WEIRD", "INTERNAL"),
        (VolumeSet(40), "TIMEOUT", "TIMEOUT"),
        (VolumeSet(40), "NOT_FOUND", "NOT_FOUND"),
    ],
)
def test_should_return_failed_when_desktop_reports_other_errors(
    events: list[str], intent: Intent, code: str, mapped: str
) -> None:
    desktop = FakeDesktop(events, error=DesktopError(code, "msg"))
    response = run(intent, desktop, "balanced", gate=allow_gate(events))
    assert response.status == "failed"
    assert error_of(response).code == mapped
    assert error_of(response).remedy
    assert validate_response(response.model_dump()).spoken == response.spoken


@pytest.mark.parametrize("name", ["clock.time", "clock.date"])
def test_should_register_clock_tools_when_importing_fastpath(name: str) -> None:
    spec = policy.get(name)
    assert spec is not None
    assert spec.tier == policy.Tier.T0
    assert spec.scopes == ()
