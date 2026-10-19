"""The GrantStore audits every change before it makes it (FR-CON-17)."""

from pathlib import Path

import pytest

from tests.store_files_rig import AuditRecords, collect_audit
from tests.store_rig import SLACK_W, TEAMS_R, TEAMS_W, make_store


@pytest.fixture
def audit_log(monkeypatch: pytest.MonkeyPatch) -> AuditRecords:
    return collect_audit(monkeypatch)


def test_should_audit_every_change_before_writing(tmp_path: Path, audit_log: AuditRecords) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.grant(SLACK_W, "never", "typed")
    store.revoke(TEAMS_R)
    store.revoke_all()
    store.reset_all_to_ask()
    assert [kw["op"] for _, kw in audit_log] == [
        "grant", "grant", "revoke", "revoke_all", "reset_all_to_ask"
    ]  # fmt: skip
    assert {m for m, _ in audit_log} == {"grant change"}
    first = audit_log[0][1]
    assert first == {
        "op": "grant", "scope": "messages.teams:read", "lifetime": "always",
        "method": "voice", "count": 1,
    }  # fmt: skip


@pytest.mark.parametrize("op", ["grant", "revoke", "revoke_all", "reset_all_to_ask"])
def test_should_change_nothing_when_the_audit_of_a_change_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, op: str
) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.grant(SLACK_W, "never", "voice")
    before = (tmp_path / "grants.json").read_bytes()

    def broken(*_a: object, **_k: object) -> None:
        raise OSError("audit down")

    monkeypatch.setattr("jarvis.consent.store.audit", broken)
    actions = {
        "grant": lambda: store.grant(TEAMS_W, "always", "voice"),
        "revoke": lambda: store.revoke(TEAMS_R),
        "revoke_all": store.revoke_all,
        "reset_all_to_ask": store.reset_all_to_ask,
    }
    with pytest.raises(OSError, match="audit down"):
        actions[op]()
    assert (tmp_path / "grants.json").read_bytes() == before
    assert len(store.all()) == 2
