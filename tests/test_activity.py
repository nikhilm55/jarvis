"""Tests for jarvis.activity."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from jarvis.activity import ActivityLog, PolicyRecord, ToolCallRecord, TurnRecord
from jarvis.contract import FinalResponse
from jarvis.paths import data_dir


def make_record(**overrides: Any) -> TurnRecord:
    """Build a TurnRecord with sensible defaults, overriding any field."""
    base: dict[str, Any] = {
        "ts": datetime(2026, 10, 7, 9, 30, tzinfo=UTC),
        "turn_id": "t1",
        "raw_transcript": "Jarvis, open Teams.",
        "command": "open Teams",
        "route": "fastpath",
    }
    base.update(overrides)
    return TurnRecord(**base)


def test_should_write_one_json_line_when_recorded(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(make_record())
    target = tmp_path / "2026-10-07.jsonl"
    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["turn_id"] == "t1"
    assert parsed["route"] == "fastpath"
    assert parsed["raw_transcript"] == "Jarvis, open Teams."
    assert parsed["command"] == "open Teams"
    assert parsed["ts"] == "2026-10-07T09:30:00+00:00"


def test_should_append_two_records_same_day_and_split_other_day_when_recorded(
    tmp_path: Path,
) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(make_record())
    log.record(make_record(turn_id="t2"))
    same_day = tmp_path / "2026-10-07.jsonl"
    assert len(same_day.read_text(encoding="utf-8").splitlines()) == 2
    log.record(make_record(ts=datetime(2026, 10, 8, 9, 30, tzinfo=UTC)))
    other_day = tmp_path / "2026-10-08.jsonl"
    assert other_day.exists()
    assert len(other_day.read_text(encoding="utf-8").splitlines()) == 1


def test_should_use_default_activity_dir_when_no_directory_given() -> None:
    log = ActivityLog()
    log.record(make_record())
    target = data_dir() / "activity" / "2026-10-07.jsonl"
    assert target.exists()


def test_should_set_file_mode_0600_and_dir_mode_0700_when_recorded(tmp_path: Path) -> None:
    directory = tmp_path / "activity"
    ActivityLog(directory=directory).record(make_record())
    assert (directory / "2026-10-07.jsonl").stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700


def test_should_redact_nested_tool_call_args_when_recorded(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(
        make_record(
            tool_calls=[
                ToolCallRecord(
                    tool="auth.login",
                    args={
                        "headers": {"Authorization": "Bearer abc123def456ghi789"},
                        "keys": ["sk-" + "a" * 20, "plain"],
                    },
                )
            ]
        )
    )
    text = (tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8")
    assert "Bearer abc123def456ghi789" not in text
    assert "sk-" + "a" * 20 not in text
    assert "Bearer ***" in text
    assert "***" in text


def test_should_redact_raw_transcript_and_command_when_recorded(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(
        make_record(
            raw_transcript="Bearer abc123def456ghi789",
            command="sk-" + "a" * 20,
        )
    )
    text = (tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8")
    assert "Bearer abc123def456ghi789" not in text
    assert "sk-" + "a" * 20 not in text
    assert "Bearer ***" in text


def test_should_serialise_final_response_when_present(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(make_record(final=FinalResponse(status="success", spoken="Done.")))
    parsed = json.loads((tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8"))
    assert parsed["final"]["spoken"] == "Done."


def test_should_keep_final_null_when_absent(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(make_record())
    parsed = json.loads((tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8"))
    assert parsed["final"] is None


def test_should_serialise_policy_decisions_and_durations_when_recorded(
    tmp_path: Path,
) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(
        make_record(
            policy_decisions=[PolicyRecord(tool="desktop.open_app", allowed=True, reason="ok")],
            durations_ms={"stt": 120},
        )
    )
    parsed = json.loads((tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8"))
    assert parsed["policy_decisions"][0] == {
        "tool": "desktop.open_app",
        "allowed": True,
        "reason": "ok",
    }
    assert parsed["durations_ms"] == {"stt": 120}


def test_should_keep_drop_reason_and_route_when_dropped(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(make_record(route="dropped", drop_reason="silence_before_ms<400"))
    parsed = json.loads((tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8"))
    assert parsed["route"] == "dropped"
    assert parsed["drop_reason"] == "silence_before_ms<400"


def test_should_write_non_ascii_as_utf8_when_recorded(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    log.record(make_record(raw_transcript="नमस्ते"))
    text = (tmp_path / "2026-10-07.jsonl").read_text(encoding="utf-8")
    assert "नमस्ते" in text


def test_should_swallow_oserror_when_directory_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "activity"
    blocker.write_text("x", encoding="utf-8")
    ActivityLog(directory=blocker).record(make_record())
    assert blocker.read_text(encoding="utf-8") == "x"


def test_should_purge_only_old_jsonl_files_when_called(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path)
    (tmp_path / "2026-09-01.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "2026-09-06.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "2026-10-07.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "bad-name.jsonl").write_text("x", encoding="utf-8")
    deleted = log.purge(retention_days=30, today=date(2026, 10, 7))
    assert deleted == 2
    assert not (tmp_path / "2026-09-01.jsonl").exists()
    assert not (tmp_path / "2026-09-06.jsonl").exists()
    assert (tmp_path / "2026-10-07.jsonl").exists()
    assert (tmp_path / "notes.txt").exists()
    assert (tmp_path / "bad-name.jsonl").exists()


def test_should_return_zero_when_purging_missing_directory(tmp_path: Path) -> None:
    log = ActivityLog(directory=tmp_path / "does-not-exist")
    assert log.purge(retention_days=30, today=date(2026, 10, 7)) == 0
