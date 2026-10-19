"""The consent broker asks once for what is missing, and honours the lifetimes (FR-CON-05..11)."""

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from jarvis.config import ConsentSettings
from jarvis.consent.broker import AskAnswer, Broker, NoAsker
from jarvis.consent.scope import Scope
from jarvis.consent.session import SessionGrants
from jarvis.consent.store import GrantStore
from jarvis.policy.decision import TurnContext
from tests.consent_rig import MAIL_R, TEAMS_R, TEAMS_W, Rig, make_rig, says

TEAMS_READ = Scope.parse(TEAMS_R)


def _rig(tmp_path: Path, mp: pytest.MonkeyPatch, *answers: AskAnswer, **kw: object) -> Rig:
    return make_rig(tmp_path, mp, *answers, **kw)  # type: ignore[arg-type]


# --- 3.4 one ask --------------------------------------------------------------------------


def test_should_ask_once_for_all_missing_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once", "button"))
    assert rig.require(TEAMS_R, TEAMS_W, MAIL_R) == "granted"
    assert len(rig.asker.asked) == 1
    scopes, reason, offer_always = rig.asker.asked[0]
    assert [str(s) for s in scopes] == [MAIL_R, TEAMS_R, TEAMS_W]
    assert (reason, offer_always) == ("to do that", True)


def test_should_hold_a_once_answer_for_the_turn_and_its_follow_ups_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"), says("no"))
    rig.session.start_turn("t1")
    rig.session.start_turn("t2", follows="t1")
    assert rig.require(TEAMS_R, turn="t1") == "granted"
    assert rig.require(TEAMS_R, turn="t2") == "granted"  # the follow-up: not asked again
    assert len(rig.asker.asked) == 1
    rig.session.end_turn("t2")
    assert rig.require(TEAMS_R, turn="t3") == "denied"  # a new command asks again
    assert len(rig.asker.asked) == 2


def test_should_hold_a_session_answer_in_memory_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("session", "typed"))
    assert rig.require(TEAMS_R, turn="t1") == "granted"
    assert rig.require(TEAMS_R, turn="t2") == "granted"
    assert len(rig.asker.asked) == 1
    assert rig.store.all() == []
    assert not (tmp_path / "grants.json").exists()
    rig.session.end("brain_reset")
    rig.asker.answers = [says("no")]
    assert rig.require(TEAMS_R, turn="t3") == "denied"


def test_should_store_an_always_answer_and_reuse_it_after_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("always", "voice"))
    assert rig.require(TEAMS_R) == "granted"
    grant = GrantStore(tmp_path / "grants.json").get(TEAMS_READ)
    assert grant is not None and (grant.lifetime, grant.method) == ("always", "voice")
    fresh = _rig(tmp_path, monkeypatch)  # a new process: no session, the same file
    assert fresh.require(TEAMS_R) == "granted"
    assert fresh.asker.asked == []


@pytest.mark.parametrize("answer", [says("no", "key"), says("timeout", "timeout")])
def test_should_deny_on_no_and_on_timeout_and_store_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: AskAnswer
) -> None:
    rig = _rig(tmp_path, monkeypatch, answer)
    assert rig.require(TEAMS_R) == "denied"
    assert rig.store.all() == []
    assert rig.require(TEAMS_R, turn="t2") == "denied"  # and asks again next time
    assert len(rig.asker.asked) == 2


def test_should_store_never_and_deny_and_stop_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("never", "typed"), says("always"))
    assert rig.require(TEAMS_R, TEAMS_W) == "denied"
    assert {(str(g.scope), g.lifetime) for g in rig.store.all()} == {
        (TEAMS_R, "never"),
        (TEAMS_W, "never"),
    }
    assert rig.require(TEAMS_R, turn="t2") == "denied"
    assert len(rig.asker.asked) == 1


def test_should_deny_when_the_asker_never_answers_in_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = ConsentSettings(ask_timeout_s=0.02)
    rig = _rig(tmp_path, monkeypatch, says("always"), settings=settings, delay_s=5)
    assert rig.require(TEAMS_R) == "denied"
    assert rig.store.all() == []
    assert rig.checks()[-1]["reason"] == "no answer"


@pytest.mark.parametrize("choice", ["once", "session", "always", "never"])
def test_should_never_grant_from_an_answer_that_came_by_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    rig = _rig(tmp_path, monkeypatch, says(choice, "timeout"))  # type: ignore[arg-type]
    assert rig.require(TEAMS_R) == "denied"
    assert rig.store.all() == []


@pytest.mark.parametrize("junk", ["yes", None, True, "ALWAYS", ""])
def test_should_treat_an_unknown_answer_as_a_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, junk: object
) -> None:
    rig = _rig(tmp_path, monkeypatch, AskAnswer(junk, "voice"))  # type: ignore[arg-type]
    assert rig.require(TEAMS_R) == "denied"
    assert rig.store.all() == []


def test_should_deny_when_the_asker_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = _rig(tmp_path, monkeypatch)

    async def boom(*_a: object, **_k: object) -> AskAnswer:
        raise RuntimeError("card crashed")

    monkeypatch.setattr(rig.asker, "ask", boom)
    assert rig.require(TEAMS_R) == "denied"
    assert rig.checks()[-1]["reason"] == "error: RuntimeError"


def test_should_deny_everything_with_the_default_no_asker(tmp_path: Path) -> None:
    broker = Broker(GrantStore(tmp_path / "g.json"), SessionGrants(), NoAsker(), ConsentSettings())
    ctx = TurnContext("t1", mode="balanced")
    assert asyncio.run(broker.require((TEAMS_R,), "x", ctx)) == "denied"


# --- Safe mode (FR-CON-11) ----------------------------------------------------------------


def test_should_ask_every_turn_in_safe_mode_even_with_an_always_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"))
    rig.store.grant(TEAMS_READ, "always", "voice")
    assert rig.require(TEAMS_R, mode="safe") == "granted"
    assert len(rig.asker.asked) == 1
    assert rig.asker.asked[0][2] is False  # no "always" on offer


def test_should_treat_an_always_answer_as_session_in_safe_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("always"), says("no"))
    rig.session.start_turn("t1")
    assert rig.require(TEAMS_R, mode="safe", turn="t1") == "granted"
    assert rig.store.all() == []  # nothing stored
    assert rig.require(TEAMS_R, mode="safe", turn="t2") == "denied"  # asked again the next turn
    assert len(rig.asker.asked) == 2
    assert rig.require(TEAMS_R, mode="balanced", turn="t3") == "granted"  # a session grant


def test_should_offer_always_outside_safe_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("no"))
    rig.require(TEAMS_R, mode="balanced")
    assert rig.asker.asked[0][2] is True


# --- Lifetimes (FR-CON-09) ----------------------------------------------------------------


def test_should_expire_an_always_grant_after_the_configured_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("no"), settings=ConsentSettings(always_expiry_days=30))
    rig.store.grant(TEAMS_READ, "always", "voice")
    rig.clock.now += timedelta(days=29, hours=23)
    assert rig.require(TEAMS_R) == "granted"
    assert rig.asker.asked == []
    rig.clock.now += timedelta(hours=1)  # 30 days since it was granted
    assert rig.require(TEAMS_R, turn="t2") == "denied"
    assert len(rig.asker.asked) == 1  # expired: it asks again


def test_should_keep_an_always_grant_until_revoked_when_no_expiry_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch)
    rig.store.grant(TEAMS_READ, "always", "voice")
    rig.clock.now = rig.clock.now.replace(year=2030)
    assert rig.require(TEAMS_R) == "granted"
    rig.broker.revoke(TEAMS_READ)
    rig.asker.answers = [says("no")]
    assert rig.require(TEAMS_R) == "denied"


def test_should_keep_a_never_until_revoked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"))
    rig.store.grant(TEAMS_READ, "never", "voice")
    rig.clock.now = rig.clock.now.replace(year=2030)
    assert rig.require(TEAMS_R) == "denied"
    rig.broker.revoke(TEAMS_READ)
    assert rig.require(TEAMS_R) == "granted"  # asks again, and the answer is once
