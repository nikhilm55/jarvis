"""Once and session grants and their lifetimes (FR-CON-09); the clock is injected, no sleeps."""

import pytest

from jarvis.consent.scope import Scope
from jarvis.consent.session import SESSION_MAX_S, EndReason, SessionGrants

TEAMS = Scope.parse("messages.teams:read")
MAIL = Scope.parse("email.outlook:read")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _grants() -> tuple[SessionGrants, Clock]:
    clock = Clock()
    return SessionGrants(clock), clock


def test_should_hold_nothing_at_first() -> None:
    grants, _ = _grants()
    assert not grants.holds(TEAMS, "t1")


def test_should_hold_a_once_grant_for_the_turn_that_got_it_and_no_other() -> None:
    grants, _ = _grants()
    grants.grant(TEAMS, "once", "t1")
    assert grants.holds(TEAMS, "t1")
    assert not grants.holds(TEAMS, "t2")
    assert not grants.holds(MAIL, "t1")


def test_should_end_a_once_grant_when_its_turn_ends() -> None:
    grants, _ = _grants()
    grants.grant(TEAMS, "once", "t1")
    grants.end_turn("t1")
    assert not grants.holds(TEAMS, "t1")


def test_should_keep_a_once_grant_through_the_follow_ups_of_its_command() -> None:
    grants, _ = _grants()
    grants.start_turn("t1")
    grants.grant(TEAMS, "once", "t1")
    grants.start_turn("t2", follows="t1")
    grants.start_turn("t3", follows="t2")  # a follow-up of a follow-up: same command
    assert grants.holds(TEAMS, "t2")
    assert grants.holds(TEAMS, "t3")
    grants.end_turn("t3")  # the command is over: all of its turns lose the grant
    assert not grants.holds(TEAMS, "t1")
    assert not grants.holds(TEAMS, "t3")


def test_should_share_a_once_grant_made_in_a_follow_up_with_the_whole_command() -> None:
    grants, _ = _grants()
    grants.start_turn("t1")
    grants.start_turn("t2", follows="t1")
    grants.grant(MAIL, "once", "t2")
    assert grants.holds(MAIL, "t1")


def test_should_not_share_a_once_grant_with_another_command() -> None:
    grants, _ = _grants()
    grants.start_turn("t1")
    grants.start_turn("t9")
    grants.grant(TEAMS, "once", "t1")
    grants.end_turn("t9")  # an unrelated command ending does not end this one
    assert grants.holds(TEAMS, "t1")
    assert not grants.holds(TEAMS, "t9")


def test_should_hold_a_session_grant_across_turns() -> None:
    grants, _ = _grants()
    grants.grant(TEAMS, "session", "t1")
    grants.end_turn("t1")
    assert grants.holds(TEAMS, "t2")


@pytest.mark.parametrize("reason", ["brain_reset", "pc_lock", "sign_out"])
def test_should_end_session_and_once_grants_on_each_session_end(reason: EndReason) -> None:
    grants, _ = _grants()
    grants.grant(TEAMS, "session", "t1")
    grants.grant(MAIL, "once", "t1")
    grants.end(reason)
    assert not grants.holds(TEAMS, "t2")
    assert not grants.holds(MAIL, "t1")


def test_should_end_a_session_grant_after_eight_hours() -> None:
    grants, clock = _grants()
    grants.grant(TEAMS, "session", "t1")
    clock.now += SESSION_MAX_S - 1
    assert grants.holds(TEAMS, "t2")
    clock.now += 1
    assert not grants.holds(TEAMS, "t2")
    assert not grants.holds(TEAMS, "t2")  # and it stays gone


def test_should_count_the_eight_hours_from_each_grant() -> None:
    grants, clock = _grants()
    grants.grant(TEAMS, "session", "t1")
    clock.now += SESSION_MAX_S - 60
    grants.grant(MAIL, "session", "t1")
    clock.now += 120
    assert not grants.holds(TEAMS, "t2")
    assert grants.holds(MAIL, "t2")


def test_should_honour_a_session_grant_from_an_earlier_command_unless_this_command_only() -> None:
    grants, _ = _grants()
    grants.start_turn("t1")
    grants.grant(TEAMS, "session", "t1")
    grants.start_turn("t2")
    assert grants.holds(TEAMS, "t2")
    assert not grants.holds(TEAMS, "t2", this_command_only=True)  # Safe mode asks every turn
    grants.start_turn("t3", follows="t1")
    assert grants.holds(TEAMS, "t3", this_command_only=True)  # but not again inside a command


def test_should_revoke_one_scope_only() -> None:
    grants, _ = _grants()
    grants.grant(TEAMS, "session", "t1")
    grants.grant(MAIL, "once", "t1")
    assert grants.revoke(TEAMS)
    assert not grants.revoke(TEAMS)
    assert not grants.holds(TEAMS, "t1")
    assert grants.holds(MAIL, "t1")


def test_should_remember_the_sources_a_yolo_run_asked_about_until_the_session_ends() -> None:
    grants, _ = _grants()
    assert not grants.seen("messages.teams")
    grants.mark_seen("messages.teams")
    assert grants.seen("messages.teams")
    grants.end("brain_reset")
    assert not grants.seen("messages.teams")


def test_should_audit_a_session_end(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "jarvis.consent.session.audit", lambda src, msg, **kw: records.append((msg, kw))
    )
    grants, _ = _grants()
    grants.grant(TEAMS, "session", "t1")
    grants.end("pc_lock")
    assert records == [("session ended", {"reason": "pc_lock", "count": 1})]


def test_should_forget_the_grants_even_when_the_audit_log_is_unwritable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jarvis.consent.session.audit", broken)
    grants, _ = _grants()
    grants.grant(TEAMS, "session", "t1")
    grants.end("sign_out")
    assert not grants.holds(TEAMS, "t1")
