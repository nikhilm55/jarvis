"""The consent broker, in the order of FRS 5.11.3: never / deny list, YOLO, grants, one ask."""

import asyncio
from pathlib import Path

import pytest

from jarvis.config import ConsentSettings, PolicySettings
from jarvis.consent.broker import AskAnswer
from jarvis.consent.scope import Scope
from jarvis.policy.decision import TurnContext
from tests.consent_rig import MAIL_R, TEAMS_R, TEAMS_W, Rig, make_rig, says

TEAMS_READ = Scope.parse(TEAMS_R)


def _rig(tmp_path: Path, mp: pytest.MonkeyPatch, *answers: AskAnswer, **kw: object) -> Rig:
    return make_rig(tmp_path, mp, *answers, **kw)  # type: ignore[arg-type]


# --- 3.1 never and the deny list: no prompt, in every mode ---------------------------------


@pytest.mark.parametrize("mode", ["safe", "balanced", "yolo"])
def test_should_deny_a_never_scope_without_asking_in_every_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"))
    rig.store.grant(TEAMS_READ, "never", "voice")
    assert rig.require(TEAMS_R, mode=mode) == "denied"  # type: ignore[arg-type]
    assert rig.asker.asked == []
    assert rig.checks()[-1]["reason"] == f"never: {TEAMS_R}"


def test_should_deny_when_any_one_scope_is_never(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"))
    rig.store.grant(Scope.parse(MAIL_R), "never", "typed")
    assert rig.require(TEAMS_R, MAIL_R) == "denied"
    assert rig.asker.asked == []


@pytest.mark.parametrize("mode", ["safe", "balanced", "yolo"])
def test_should_deny_a_deny_listed_path_without_asking_in_every_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("always"))
    secret = tmp_path / "secrets" / "key.txt"
    policy = PolicySettings(deny_paths=[str(secret.parent)])
    ctx = TurnContext("t1", policy, mode=mode)  # type: ignore[arg-type]
    verdict = asyncio.run(
        rig.broker.require(("files.documents:read",), "x", ctx, args={"path": str(secret)})
    )
    assert verdict == "denied"
    assert rig.asker.asked == []
    assert str(rig.checks()[-1]["reason"]).startswith("deny list:")


def test_should_allow_a_path_that_is_not_deny_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"))
    assert rig.require(TEAMS_R, args={"path": str(tmp_path / "ok.txt")}) == "granted"


# --- 3.2 YOLO -----------------------------------------------------------------------------


def test_should_auto_allow_in_yolo_and_audit_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch)
    assert rig.require(TEAMS_R, MAIL_R, mode="yolo") == "granted"
    assert rig.asker.asked == []
    check = rig.checks()[-1]
    assert (check["reason"], check["method"], check["mode"]) == (
        "auto-allowed: YOLO",
        "yolo",
        "yolo",
    )


def test_should_ask_on_the_first_touch_of_each_source_when_the_yolo_switch_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = ConsentSettings(yolo_asks_first_touch=True)
    rig = _rig(tmp_path, monkeypatch, says("once"), settings=settings)
    assert rig.require(TEAMS_R, mode="yolo") == "granted"
    assert len(rig.asker.asked) == 1
    assert rig.require(TEAMS_W, mode="yolo", turn="t2") == "granted"  # same source: not asked
    assert len(rig.asker.asked) == 1
    assert rig.require(MAIL_R, mode="yolo", turn="t3") == "granted"  # a new source: asked
    assert len(rig.asker.asked) == 2


def test_should_deny_in_yolo_when_the_first_touch_question_is_refused_and_ask_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = ConsentSettings(yolo_asks_first_touch=True)
    rig = _rig(tmp_path, monkeypatch, says("no", "key"), says("session"), settings=settings)
    assert rig.require(TEAMS_R, mode="yolo") == "denied"
    assert rig.require(TEAMS_R, mode="yolo", turn="t2") == "granted"
    assert len(rig.asker.asked) == 2


# --- 3.3 existing grants ------------------------------------------------------------------


def test_should_grant_from_an_always_grant_and_record_the_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch)
    rig.store.grant(TEAMS_READ, "always", "voice")
    rig.clock.now = rig.clock.now.replace(hour=11)
    assert rig.require(TEAMS_R) == "granted"
    assert rig.asker.asked == []
    grant = rig.store.get(TEAMS_READ)
    assert grant is not None and grant.last_used == rig.clock.now
    assert rig.checks()[-1]["method"] == "grant"


def test_should_ask_only_for_the_scopes_that_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("once"))
    rig.store.grant(TEAMS_READ, "always", "voice")
    assert rig.require(TEAMS_R, TEAMS_W) == "granted"
    assert [s[0] for s in rig.asker.asked] == [(Scope.parse(TEAMS_W),)]


def test_should_not_treat_a_read_grant_as_a_write_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path, monkeypatch, says("no"))
    rig.store.grant(TEAMS_READ, "always", "voice")
    assert rig.require(TEAMS_W) == "denied"
