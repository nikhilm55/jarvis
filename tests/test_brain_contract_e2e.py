"""The respond contract through the real MCP server and a fake claude (R24, FR-IO-06)."""

import logging
from pathlib import Path

import pytest

from jarvis.contract import FALLBACK_SPOKEN
from tests.brain_rig import INVALID, finish, play, respond


def test_should_repair_exactly_once_when_the_first_respond_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses, _, fake = play(tmp_path, monkeypatch, [finish(respond(INVALID), respond())])
    first, second = fake.tool_calls()
    assert first["is_error"] is True
    assert "failed validation" in first["text"]
    assert (second["is_error"], second["text"]) == (False, "ok")
    assert (responses[0].status, responses[0].spoken) == ("success", "Done.")


def test_should_fall_back_when_the_brain_responds_invalid_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        responses, _, _ = play(tmp_path, monkeypatch, [finish(respond(INVALID), respond(INVALID))])
    assert responses[0].status == "failed"
    assert responses[0].spoken == FALLBACK_SPOKEN
    assert responses[0].error is not None
    assert responses[0].error.code == "INTERNAL"
    assert "contract violation" in [r.getMessage() for r in caplog.records]


def test_should_wrap_the_bare_text_when_the_brain_never_responds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        responses, _, _ = play(tmp_path, monkeypatch, [[{"result": "Calculator is open."}]])
    assert (responses[0].status, responses[0].spoken) == ("partial", "Calculator is open.")
    assert "contract violation" in [r.getMessage() for r in caplog.records]


def test_should_tell_the_brain_to_respond_when_max_steps_is_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    volume = {"call": "volume_get", "args": {}}
    turn = finish(volume, volume, respond())
    responses, _, fake = play(tmp_path, monkeypatch, [turn], max_steps=1)
    second = fake.tool_calls()[1]
    assert second["is_error"] is True
    assert "respond now" in second["text"]
    assert responses[0].status == "success"
