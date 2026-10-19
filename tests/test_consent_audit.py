"""Consent audit (FR-CON-17) and the broker's fail-closed rule: every doubt is a no."""

import asyncio
import json
from pathlib import Path

import pytest

from jarvis import paths
from jarvis.config import ConsentSettings
from jarvis.consent.broker import Broker, NoAsker
from jarvis.consent.scope import Scope
from jarvis.consent.session import SessionGrants
from jarvis.consent.store import GrantStore, GrantsWriteError
from jarvis.policy.decision import TurnContext
from tests.consent_rig import MAIL_R, TEAMS_R, make_rig, says

TEAMS_READ = Scope.parse(TEAMS_R)


def test_should_audit_the_prompt_the_answer_and_the_check_with_turn_scopes_mode_and_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("session", "typed"))
    rig.require(TEAMS_R, MAIL_R, mode="balanced", turn="turn-7")
    by_message = {message: fields for message, fields in rig.audit if message.startswith("consent")}
    assert set(by_message) == {"consent prompt", "consent answer", "consent check"}
    scopes = f"{MAIL_R},{TEAMS_R}"
    assert by_message["consent prompt"] == {
        "turn_id": "turn-7", "scopes": scopes, "mode": "balanced",
        "decision": "asking", "method": "ask", "reason": "to do that",
    }  # fmt: skip
    for message in ("consent answer", "consent check"):
        fields = by_message[message]
        assert (fields["turn_id"], fields["mode"], fields["decision"]) == (
            "turn-7", "balanced", "granted",
        )  # fmt: skip
        assert (fields["method"], fields["reason"]) == ("typed", "session")


def test_should_audit_a_denied_answer_with_its_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "button"))
    rig.require(TEAMS_R)
    check = rig.checks()[-1]
    assert (check["decision"], check["method"], check["reason"]) == ("denied", "button", "no")


def test_should_audit_a_grant_change_before_it_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always", "voice"))
    rig.require(TEAMS_R)
    changes = [kw for msg, kw in rig.audit if msg == "grant change"]
    assert changes == [
        {"op": "grant", "scope": TEAMS_R, "lifetime": "always", "method": "voice", "count": 1}
    ]


def test_should_audit_a_revoke_and_a_session_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch)
    rig.store.grant(TEAMS_READ, "always", "voice")
    rig.audit.clear()
    rig.broker.revoke(TEAMS_READ)
    rig.broker.revoke_all()
    messages = [msg for msg, _ in rig.audit]
    assert messages == ["grant change", "grant change", "session ended"]


def test_should_write_real_audit_records_to_the_audit_log(tmp_path: Path) -> None:
    broker = Broker(GrantStore(tmp_path / "g.json"), SessionGrants(), NoAsker(), ConsentSettings())
    asyncio.run(broker.require((TEAMS_R,), "x", TurnContext("turn-9", mode="balanced")))
    log = paths.data_dir() / "logs" / "audit.jsonl"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    consent = [r for r in rows if r["name"] == "jarvis.consent"]
    assert [r["msg"] for r in consent] == ["consent prompt", "consent answer", "consent check"]
    assert consent[-1]["turn_id"] == "turn-9"
    assert consent[-1]["decision"] == "denied"


def test_should_deny_when_the_audit_log_is_unwritable_even_for_a_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch)
    rig.store.grant(TEAMS_READ, "always", "voice")

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jarvis.consent.broker.audit", broken)
    assert rig.require(TEAMS_R) == "denied"


def test_should_deny_when_the_prompt_cannot_be_audited_and_not_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always"))

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jarvis.consent.broker.audit", broken)
    assert rig.require(TEAMS_R) == "denied"
    assert rig.asker.asked == []
    assert rig.store.all() == []


@pytest.mark.parametrize("bad", ["", "messages.teams", "messages.teams:record", "bad source:read"])
def test_should_deny_a_malformed_scope_without_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always"))
    assert rig.require(bad) == "denied"
    assert rig.asker.asked == []
    assert str(rig.checks()[-1]["reason"]).startswith("malformed scope")


def test_should_deny_when_an_always_answer_cannot_be_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always", "voice"))

    def fail(*_args: object, **_kwargs: object) -> None:
        raise GrantsWriteError("read-only disk")

    monkeypatch.setattr(rig.store, "grant", fail)
    assert rig.require(TEAMS_R) == "denied"
    assert rig.checks()[-1]["reason"] == "error: GrantsWriteError"


def test_should_deny_when_the_last_used_stamp_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch)
    rig.store.grant(TEAMS_READ, "always", "voice")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise GrantsWriteError("read-only disk")

    monkeypatch.setattr(rig.store, "touch", fail)
    assert rig.require(TEAMS_R) == "denied"


def test_should_ask_again_instead_of_trusting_a_damaged_grants_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "grants.json").write_text('{"version": 1, "grants": [{"scope": ', encoding="utf-8")
    rig = make_rig(tmp_path, monkeypatch, says("no"))
    assert rig.store.problem is not None
    assert rig.require(TEAMS_R) == "denied"
    assert len(rig.asker.asked) == 1  # no grant was assumed


def test_should_grant_an_empty_request_without_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no"))
    assert rig.require() == "granted"
    assert rig.asker.asked == []


def test_should_forget_session_grants_when_everything_is_revoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("session"), says("no"))
    assert rig.require(TEAMS_R) == "granted"
    rig.broker.revoke_all()
    assert rig.require(TEAMS_R, turn="t2") == "denied"


def test_should_forget_even_never_entries_on_reset_all_to_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("once"))
    rig.store.grant(TEAMS_READ, "never", "voice")
    rig.broker.reset_all_to_ask()
    assert rig.require(TEAMS_R) == "granted"
    assert len(rig.asker.asked) == 1


def test_should_expand_a_star_scope_to_read_and_write_and_ask_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("once"))
    assert rig.require("messages.teams:*") == "granted"
    assert [str(s) for s in rig.asker.asked[0][0]] == [TEAMS_R, "messages.teams:write"]
