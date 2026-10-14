import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

from jarvis.activity import TurnRecord

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "acceptance_report", ROOT / "scripts" / "acceptance_report.py"
)
assert spec and spec.loader
report = importlib.util.module_from_spec(spec)
sys.modules["acceptance_report"] = report
spec.loader.exec_module(report)


def test_should_return_none_when_median_called_with_empty_list() -> None:
    assert report.median([]) is None


def test_should_return_middle_value_when_median_called_with_odd_count() -> None:
    assert report.median([1.0, 3.0, 5.0]) == 3.0


def test_should_return_mean_of_two_middle_when_median_called_with_even_count() -> None:
    assert report.median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_should_return_dash_when_fmt_ms_called_with_none() -> None:
    assert report.fmt_ms(None) == "-"


def test_should_return_rounded_string_when_fmt_ms_called_with_float() -> None:
    assert report.fmt_ms(123.456) == "123"


def test_should_build_row_with_record_fields_when_row_from_record_called_with_record() -> None:
    rec = TurnRecord(
        ts=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        turn_id="t1",
        raw_transcript="Jarvis, open Calculator.",
        command="open Calculator",
        route="fastpath",
        durations_ms={"stt": 210, "total": 1500},
    )
    row = report.row_from_record(
        "calc", 1, rec, outcome="PASS", eos_to_audio_ms=100, eos_to_speech_ms=200, action_ms=50
    )
    assert row.heard == "Jarvis, open Calculator."
    assert row.route == "fastpath"
    assert row.stt_ms == 210
    assert row.total_ms == 1500
    assert row.passed is True


def test_should_build_empty_row_when_row_from_record_called_with_none_record() -> None:
    row = report.row_from_record(
        "calc", 2, None, outcome="FAIL", eos_to_audio_ms=None, eos_to_speech_ms=None, action_ms=None
    )
    assert row.heard == ""
    assert row.route == "none"
    assert row.stt_ms is None
    assert row.total_ms is None
    assert row.passed is False


def test_should_produce_correct_line_count_when_results_table_called() -> None:
    rows = [
        report.Row("a", 1, "h1", "r1", "PASS", 1, 2, 3, 4, 5),
        report.Row("b", 2, "h2", "r2", "FAIL", 1, 2, 3, 4, 5),
    ]
    text = report.results_table(rows)
    lines = text.splitlines()
    assert len(lines) == 4


def test_should_replace_pipe_in_heard_when_results_table_called() -> None:
    rows = [report.Row("a", 1, "x|y", "r", "PASS", 1, 2, 3, 4, 5)]
    text = report.results_table(rows)
    assert "`x/y`" in text
    assert "`x|y`" not in text


def test_should_group_by_case_in_first_seen_order_when_summary_table_called() -> None:
    rows = [
        report.Row("b", 1, "h", "r", "PASS", 1, 2, 3, 4, 5),
        report.Row("a", 1, "h", "r", "PASS", 1, 2, 3, 4, 5),
        report.Row("b", 2, "h", "r", "FAIL", 1, 2, 3, 4, 5),
    ]
    text = report.summary_table(rows)
    lines = text.splitlines()
    assert "b" in lines[2]
    assert "a" in lines[3]


def test_should_show_passed_ratio_when_summary_table_called() -> None:
    rows = [
        report.Row("a", 1, "h", "r", "PASS", 1, 2, 3, 4, 5),
        report.Row("a", 2, "h", "r", "FAIL", 1, 2, 3, 4, 5),
    ]
    text = report.summary_table(rows)
    assert "1/2" in text


def test_should_ignore_none_values_when_summary_table_computes_p50() -> None:
    rows = [
        report.Row("a", 1, "h", "r", "PASS", 10, None, 3, 4, 5),
        report.Row("a", 2, "h", "r", "PASS", 20, None, 3, 4, 5),
    ]
    text = report.summary_table(rows)
    assert "15" in text


def test_should_return_true_when_spoken_time_matches_within_tolerance() -> None:
    now = datetime(2026, 10, 13, 15, 42, tzinfo=UTC)
    assert report.spoken_time_matches("It's 3:42 PM.", now) is True


def test_should_return_false_when_spoken_time_matches_outside_tolerance() -> None:
    now = datetime(2026, 10, 13, 15, 42, tzinfo=UTC)
    assert report.spoken_time_matches("It's 3:45 PM.", now) is False


def test_should_parse_12am_as_hour_zero_when_spoken_time_matches_called() -> None:
    now = datetime(2026, 10, 13, 0, 5, tzinfo=UTC)
    assert report.spoken_time_matches("It's 12:05 AM.", now) is True


def test_should_parse_12pm_as_hour_twelve_when_spoken_time_matches_called() -> None:
    now = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)
    assert report.spoken_time_matches("It's 12:30 PM.", now) is True


def test_should_wrap_around_midnight_when_spoken_time_matches_called() -> None:
    now = datetime(2026, 10, 13, 23, 59, tzinfo=UTC)
    assert report.spoken_time_matches("It's 12:01 AM.", now) is True


def test_should_return_false_when_spoken_time_matches_called_with_garbage() -> None:
    now = datetime(2026, 10, 13, 15, 42, tzinfo=UTC)
    assert report.spoken_time_matches("hello world", now) is False


def test_should_compute_percent_when_cpu_percent_called_with_positive_wall() -> None:
    assert report.cpu_percent(1.5, 2.0) == 75.0


def test_should_return_zero_when_cpu_percent_called_with_zero_wall() -> None:
    assert report.cpu_percent(1.5, 0.0) == 0.0
