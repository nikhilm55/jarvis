"""Helpers shared by the GrantStore tests: a store on a fixed clock."""

from datetime import UTC, datetime
from pathlib import Path

from jarvis.consent.scope import Scope
from jarvis.consent.store import GrantStore

TEAMS_R = Scope.parse("messages.teams:read")
TEAMS_W = Scope.parse("messages.teams:write")
SLACK_W = Scope.parse("messages.slack:write")
T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def make_store(tmp_path: Path, clock: datetime = T0) -> GrantStore:
    return GrantStore(tmp_path / "grants.json", clock=lambda: clock)
