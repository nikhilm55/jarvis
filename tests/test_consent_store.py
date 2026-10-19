"""The consent GrantStore (R87): grants, lifetimes and the file format."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.store_rig import (
    SLACK_W,
    T0,
    TEAMS_R,
    TEAMS_W,
    make_store,
)

# --- the grants and the file format -------------------------------------------------------


def test_should_start_empty_and_create_nothing_when_the_file_is_missing(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.all() == []
    assert store.get(TEAMS_R) is None
    assert store.problem is None
    assert list(tmp_path.iterdir()) == []


def test_should_round_trip_a_grant_through_a_newmake_store(tmp_path: Path) -> None:
    grant = make_store(tmp_path).grant(TEAMS_R, "always", "voice")
    assert (grant.scope, grant.lifetime, grant.method) == (TEAMS_R, "always", "voice")
    assert grant.granted_at == T0 and grant.last_used is None
    assert make_store(tmp_path).get(TEAMS_R) == grant


def test_should_write_exactly_the_documented_format(tmp_path: Path) -> None:
    make_store(tmp_path).grant(TEAMS_R, "always", "voice")
    expected = {
        "version": 1,
        "grants": [
            {
                "scope": "messages.teams:read",
                "lifetime": "always",
                "method": "voice",
                "granted_at": "2026-10-16T09:00:00Z",
                "last_used": None,
            }
        ],
    }
    text = (tmp_path / "grants.json").read_text(encoding="utf-8")
    assert text == json.dumps(expected, indent=2, sort_keys=True) + "\n"


def test_should_keep_the_grants_sorted_by_scope_on_disk_and_in_all(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for scope in (SLACK_W, TEAMS_W, TEAMS_R):
        store.grant(scope, "always", "typed")
    names = [str(g.scope) for g in store.all()]
    assert names == ["messages.slack:write", "messages.teams:read", "messages.teams:write"]
    on_disk = json.loads((tmp_path / "grants.json").read_text(encoding="utf-8"))
    assert [g["scope"] for g in on_disk["grants"]] == names


@pytest.mark.parametrize("lifetime", ["once", "session", "forever", ""])
def test_should_store_only_always_and_never(tmp_path: Path, lifetime: str) -> None:
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="stored"):
        store.grant(TEAMS_R, lifetime, "voice")  # type: ignore[arg-type]
    assert not (tmp_path / "grants.json").exists()


def test_should_refuse_an_unknown_method(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="method"):
        make_store(tmp_path).grant(TEAMS_R, "always", "telepathy")  # type: ignore[arg-type]


def test_should_replace_the_earlier_grant_of_a_scope(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.touch(TEAMS_R)
    later = T0 + timedelta(days=1)
    replaced = make_store(tmp_path, later).grant(TEAMS_R, "never", "typed")
    assert (replaced.lifetime, replaced.method) == ("never", "typed")
    assert (replaced.granted_at, replaced.last_used) == (later, None)
    assert len(make_store(tmp_path).all()) == 1


def test_should_revoke_one_scope_and_say_whether_it_was_there(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.grant(TEAMS_W, "always", "voice")
    assert store.revoke(TEAMS_R) is True
    assert store.revoke(TEAMS_R) is False
    assert [g.scope for g in make_store(tmp_path).all()] == [TEAMS_W]


def test_should_revoke_all_always_grants_and_keep_the_never_ones(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.grant(TEAMS_W, "always", "voice")
    store.grant(SLACK_W, "never", "typed")
    assert store.revoke_all() == 2
    assert [(g.scope, g.lifetime) for g in make_store(tmp_path).all()] == [(SLACK_W, "never")]


def test_should_reset_every_grant_including_never_to_ask(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.grant(SLACK_W, "never", "typed")
    assert store.reset_all_to_ask() == 2
    assert make_store(tmp_path).all() == []
