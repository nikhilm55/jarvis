"""Tests for jarvis.brain.respond.RespondGate: validate, one repair, then the fallback."""

import logging

import pytest

from jarvis.brain.failures import ToolError, step_limit_response
from jarvis.brain.respond import RespondGate
from jarvis.contract import FALLBACK_SPOKEN, FinalResponse

VALID: dict[str, object] = {"status": "success", "spoken": "Done."}
INVALID: dict[str, object] = {"status": "bogus", "spoken": "x"}


def make() -> tuple[RespondGate, list[FinalResponse]]:
    finished: list[FinalResponse] = []
    return RespondGate("t1", finished.append), finished


def test_should_resolve_the_turn_when_the_payload_is_valid() -> None:
    gate, finished = make()
    assert gate.submit(VALID) == "ok"
    assert finished == [gate.final]
    assert gate.final is not None
    assert gate.final.spoken == "Done."


def test_should_sanitise_spoken_when_the_payload_has_markup() -> None:
    gate, _ = make()
    gate.submit({"status": "success", "spoken": "**Done** now."})
    assert gate.final is not None
    assert gate.final.spoken == "Done now."


def test_should_reject_a_second_valid_respond_when_the_turn_is_resolved() -> None:
    gate, finished = make()
    gate.submit(VALID)
    with pytest.raises(ToolError, match="already"):
        gate.submit(VALID)
    assert len(finished) == 1


def test_should_repair_exactly_once_when_the_first_payload_is_invalid() -> None:
    gate, finished = make()
    with pytest.raises(ToolError, match="failed validation"):
        gate.submit(INVALID)
    assert finished == []
    assert gate.repair_used is True
    assert gate.submit(VALID) == "ok"
    assert len(finished) == 1


def test_should_fall_back_when_the_payload_is_invalid_twice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gate, finished = make()
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        with pytest.raises(ToolError):
            gate.submit(INVALID)
        gate.submit(INVALID)
    assert len(finished) == 1
    assert finished[0].status == "failed"
    assert finished[0].spoken == FALLBACK_SPOKEN
    assert finished[0].error is not None
    assert finished[0].error.code == "INTERNAL"
    assert [r.getMessage() for r in caplog.records].count("contract violation") == 2


def test_should_keep_the_first_response_when_force_is_called_twice() -> None:
    gate, finished = make()
    gate.force(step_limit_response(3))
    gate.force(FinalResponse(status="success", spoken="Late."))
    assert len(finished) == 1
    assert finished[0].status == "partial"
