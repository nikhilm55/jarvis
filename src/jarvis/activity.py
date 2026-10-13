"""Per-turn activity log: one redacted JSON line per turn (FR-LOG-01/03)."""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from jarvis.contract import FinalResponse
from jarvis.log import get_logger, redact
from jarvis.paths import data_dir

logger = get_logger("activity")

Route = Literal["fastpath", "brain", "dropped"]

_TYPING_TOOLS = re.compile(r"^desktop\.(type|paste|send_keys|key)")

_REDACT_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "apikey",
    "key",
    "authorization",
    "cookie",
    "setcookie",
}

_REDACT_SUFFIXES = (
    "password",
    "secret",
    "token",
    "apikey",
    "accesskey",
    "secretkey",
    "privatekey",
)


def _normalise_key(key: str) -> str:
    """Return the lowercase alphanumeric form of a key."""
    return "".join(ch for ch in key.lower() if ch.isalnum())


def _is_redact_key(key: str) -> bool:
    """Return True if the key name matches a redaction rule."""
    norm = _normalise_key(key)
    if norm in _REDACT_KEYS:
        return True
    return any(norm.endswith(suffix) for suffix in _REDACT_SUFFIXES)


@dataclass(frozen=True)
class ToolCallRecord:
    """A single tool invocation captured during a turn."""

    tool: str
    args: dict[str, object]


@dataclass(frozen=True)
class PolicyRecord:
    """A policy decision taken for a tool call during a turn."""

    tool: str
    allowed: bool
    reason: str


@dataclass
class TurnRecord:
    """One turn of conversation, ready to be appended to the activity log."""

    ts: datetime
    turn_id: str
    raw_transcript: str
    command: str
    route: Route
    brain_model: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    policy_decisions: list[PolicyRecord] = field(default_factory=list)
    final: FinalResponse | None = None
    durations_ms: dict[str, int] = field(default_factory=dict)
    drop_reason: str | None = None

    def to_json(self) -> str:
        """Serialize the record to a single redacted JSON line."""
        tool_calls: list[dict[str, object]] = []
        for tc in self.tool_calls:
            args: dict[str, object] = dict(tc.args)
            if _TYPING_TOOLS.match(tc.tool):
                args = {k: "***" for k in args}
            tool_calls.append({"tool": tc.tool, "args": args})
        tree: dict[str, object] = {
            "ts": self.ts.isoformat(),
            "turn_id": self.turn_id,
            "raw_transcript": self.raw_transcript,
            "command": self.command,
            "route": self.route,
            "brain_model": self.brain_model,
            "tool_calls": tool_calls,
            "policy_decisions": [
                {"tool": pd.tool, "allowed": pd.allowed, "reason": pd.reason}
                for pd in self.policy_decisions
            ],
            "final": (None if self.final is None else self.final.model_dump(mode="json")),
            "durations_ms": self.durations_ms,
            "drop_reason": self.drop_reason,
        }
        redacted = _redact_tree(tree)
        return json.dumps(redacted, ensure_ascii=False)


def _redact_tree(value: object) -> object:
    """Recursively redact strings and recurse into dicts and lists."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_redact_key(k):
                result[k] = "***"
            else:
                result[k] = _redact_tree(v)
        return result
    if isinstance(value, list):
        return [_redact_tree(item) for item in value]
    return value


class ActivityLog:
    """Append-only per-day JSONL activity log with retention purge."""

    def __init__(self, directory: Path | None = None) -> None:
        """Create a log rooted at directory, defaulting to data_dir()/activity."""
        self._directory = directory if directory is not None else data_dir() / "activity"
        self._warned = False

    def record(self, record: TurnRecord) -> None:
        """Append one redacted JSON line for the turn, never raising."""
        try:
            file = self._directory / f"{record.ts.date().isoformat()}.jsonl"
            if not self._directory.exists():
                self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(self._directory, 0o700)
            line = record.to_json()
            fd = os.open(file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)
        except Exception:
            if not self._warned:
                logger.warning("could not write the activity record", exc_info=True)
                self._warned = True
            else:
                logger.debug("could not write the activity record", exc_info=True)

    def purge(self, retention_days: int, today: date | None = None) -> int:
        """Delete activity files older than retention_days; return count removed."""
        if today is None:
            today = date.today()
        cutoff = today - timedelta(days=retention_days)
        if not self._directory.exists():
            return 0
        removed = 0
        for path in self._directory.glob("*.jsonl"):
            file_date = _file_date(path)
            if file_date is not None and file_date < cutoff:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("could not purge %s", path.name, exc_info=True)
                else:
                    removed += 1
        return removed


def _file_date(path: Path) -> date | None:
    """Parse the ISO date from a jsonl filename stem, or None if invalid."""
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None
