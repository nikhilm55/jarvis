"""Tests for activity redaction by key name, typed text and a record() that never raises."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.activity import ActivityLog, ToolCallRecord, TurnRecord


def make(*calls: ToolCallRecord) -> TurnRecord:
    return TurnRecord(
        ts=datetime(2026, 10, 7, 9, 30, tzinfo=UTC),
        turn_id="t1",
        raw_transcript="Jarvis, do it.",
        command="do it",
        route="brain",
        tool_calls=list(calls),
    )


def args_of(record: TurnRecord, index: int = 0) -> dict[str, object]:
    args: dict[str, object] = json.loads(record.to_json())["tool_calls"][index]["args"]
    return args


@pytest.mark.parametrize(
    "name",
    [
        "password",
        "Password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apiKey",
        "key",
        "Authorization",
        "cookie",
        "Set-Cookie",
        "db_password",
        "client_secret",
        "access_token",
        "private-key",
    ],
)
def test_should_redact_value_when_key_name_is_sensitive(name: str) -> None:
    call = ToolCallRecord("tool", {name: "hunter2-visible", "query": "calculator"})
    record = make(call)
    args = args_of(record)
    assert args[name] == "***"
    assert args["query"] == "calculator"


def test_should_redact_nested_containers_when_key_is_sensitive() -> None:
    call = ToolCallRecord("tool", {"token": {"a": 1}, "password": ["x", "y"]})
    record = make(call)
    args = args_of(record)
    assert args == {"token": "***", "password": "***"}


def test_should_recurse_into_nested_non_sensitive_containers() -> None:
    call = ToolCallRecord(
        "tool",
        {"headers": {"Authorization": "Bearer abc123def456ghi789", "Accept": "json"}},
    )
    record = make(call)
    args = args_of(record)
    headers = args["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "***"
    assert headers["Accept"] == "json"


@pytest.mark.parametrize(
    "tool",
    [
        "desktop.type",
        "desktop.type_text",
        "desktop.paste",
        "desktop.send_keys",
        "desktop.key_press",
    ],
)
def test_should_redact_all_args_when_tool_is_desktop_input(tool: str) -> None:
    call = ToolCallRecord(tool, {"text": "my private note", "delay": 5})
    record = make(call)
    args = args_of(record)
    assert set(args.keys()) == {"text", "delay"}
    assert all(v == "***" for v in args.values())


def test_should_keep_args_when_tool_is_other_desktop() -> None:
    call = ToolCallRecord("desktop.open_app", {"query": "calculator"})
    record = make(call)
    args = args_of(record)
    assert args == {"query": "calculator"}


def test_should_not_raise_and_not_write_when_args_not_serialisable(tmp_path: Path) -> None:
    call = ToolCallRecord("tool", {"x": object()})
    log = ActivityLog(directory=tmp_path)
    log.record(make(call))
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            assert "object" not in content


def test_should_warn_only_first_failure_when_serialisation_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="jarvis.activity")
    log = ActivityLog(directory=tmp_path)
    bad = ToolCallRecord("tool", {"x": object()})
    log.record(make(bad))
    log.record(make(bad))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
