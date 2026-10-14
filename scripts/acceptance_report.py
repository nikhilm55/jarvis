"""Acceptance report helpers for Jarvis voice turns."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from jarvis.activity import TurnRecord

__all__ = [
    "Row",
    "cpu_percent",
    "fmt_ms",
    "median",
    "results_table",
    "row_from_record",
    "spoken_time_matches",
    "summary_table",
]


@dataclass(frozen=True)
class Row:
    """One acceptance-test run row."""

    case: str
    run: int
    heard: str
    route: str
    outcome: str
    eos_to_audio_ms: int | None
    eos_to_speech_ms: int | None
    stt_ms: int | None
    action_ms: int | None
    total_ms: int | None

    @property
    def passed(self) -> bool:
        """True when the outcome is PASS."""
        return self.outcome == "PASS"


def median(values: Sequence[float]) -> float | None:
    """Return the median of values, or None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2 == 0:
        return (ordered[mid - 1] + ordered[mid]) / 2.0
    return float(ordered[mid])


def fmt_ms(value: float | None) -> str:
    """Format a millisecond value, or '-' when None."""
    if value is None:
        return "-"
    return str(round(value))


def row_from_record(  # noqa: PLR0913 - one row, many measurements
    case: str,
    run: int,
    record: TurnRecord | None,
    *,
    outcome: str,
    eos_to_audio_ms: int | None,
    eos_to_speech_ms: int | None,
    action_ms: int | None,
) -> Row:
    """Build a Row from an optional TurnRecord plus measured latencies."""
    if record is None:
        heard = ""
        route = "none"
        stt_ms: int | None = None
        total_ms: int | None = None
    else:
        heard = record.raw_transcript
        route = record.route
        stt_ms = record.durations_ms.get("stt")
        total_ms = record.durations_ms.get("total")
    return Row(
        case=case,
        run=run,
        heard=heard,
        route=route,
        outcome=outcome,
        eos_to_audio_ms=eos_to_audio_ms,
        eos_to_speech_ms=eos_to_speech_ms,
        stt_ms=stt_ms,
        action_ms=action_ms,
        total_ms=total_ms,
    )


def results_table(rows: Sequence[Row]) -> str:
    """Render rows as a Markdown results table."""
    columns = "Case|Run|Heard|Route|Outcome|EoS->audio ms|EoS->speech ms|STT ms|Action ms|Total ms"
    header = "| " + columns.replace("|", " | ") + " |"
    separator = "|---|---|---|---|---|---|---|---|---|---|"
    lines = [header, separator]
    for row in rows:
        heard = f"`{row.heard.replace('|', '/')}`"
        lines.append(
            f"| {row.case} | {row.run} | {heard} | {row.route} | {row.outcome} "
            f"| {fmt_ms(row.eos_to_audio_ms)} | {fmt_ms(row.eos_to_speech_ms)} "
            f"| {fmt_ms(row.stt_ms)} | {fmt_ms(row.action_ms)} | {fmt_ms(row.total_ms)} |"
        )
    return "\n".join(lines)


def summary_table(rows: Sequence[Row]) -> str:
    """Render a per-case summary Markdown table."""
    columns = "Case|Route|Passed|p50 EoS->audio ms|p50 EoS->speech ms|p50 STT ms|p50 Action ms"
    header = "| " + columns.replace("|", " | ") + " |"
    separator = "|---|---|---|---|---|---|---|"
    lines = [header, separator]
    seen: list[str] = []
    for row in rows:
        if row.case not in seen:
            seen.append(row.case)
    for case in seen:
        case_rows = [r for r in rows if r.case == case]
        route = case_rows[0].route
        passed_count = sum(1 for r in case_rows if r.passed)
        passed = f"{passed_count}/{len(case_rows)}"
        audio_vals = [r.eos_to_audio_ms for r in case_rows if r.eos_to_audio_ms is not None]
        speech_vals = [r.eos_to_speech_ms for r in case_rows if r.eos_to_speech_ms is not None]
        stt_vals = [r.stt_ms for r in case_rows if r.stt_ms is not None]
        action_vals = [r.action_ms for r in case_rows if r.action_ms is not None]
        lines.append(
            f"| {case} | {route} | {passed} | {fmt_ms(median(audio_vals))} "
            f"| {fmt_ms(median(speech_vals))} | {fmt_ms(median(stt_vals))} "
            f"| {fmt_ms(median(action_vals))} |"
        )
    return "\n".join(lines)


def spoken_time_matches(spoken: str, now: datetime, tolerance_min: int = 2) -> bool:
    """Check if spoken time is within tolerance of now."""
    match = re.search(r"it's\s+(\d{1,2}):(\d{2})\s*([ap])\.?m", spoken, re.IGNORECASE)
    if not match:
        return False
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3).upper()
    if hour == 12:
        hour = 0 if meridiem == "A" else 12
    elif meridiem == "P":
        hour += 12
    spoken_minutes = hour * 60 + minute
    now_minutes = now.hour * 60 + now.minute
    diff = abs(spoken_minutes - now_minutes)
    diff = min(diff, 1440 - diff)
    return diff <= tolerance_min


def cpu_percent(cpu_seconds: float, wall_seconds: float) -> float:
    """Return CPU usage as a percentage of wall time."""
    if wall_seconds <= 0:
        return 0.0
    return round(100.0 * cpu_seconds / wall_seconds, 2)
