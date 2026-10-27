"""Loading a damaged or hostile grants file fails closed and never overwrites it (R87)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.consent.scope import Scope
from jarvis.consent.store import GrantStore
from tests.store_files_rig import AuditRecords, collect_audit, entry, posix_only, write_doc
from tests.store_rig import T0, TEAMS_R, make_store

# --- loading adversarial files: fail closed, never overwrite ------------------------------

_BAD_FILES = {
    "truncated json": b'{"version": 1, "gra',
    "empty file": b"",
    "not an object": b"[]",
    "grants is a dict": b'{"version": 1, "grants": {}}',
    "grants is a string": b'{"version": 1, "grants": "none"}',
    "extra top-level key": b'{"version": 1, "grants": [], "extra": true}',
    "missing grants": b'{"version": 1}',
    "future version": b'{"version": 2, "grants": []}',
    "version zero": b'{"version": 0, "grants": []}',
    "version true": b'{"version": true, "grants": []}',
    "version a string": b'{"version": "1", "grants": []}',
    "entry not an object": b'{"version": 1, "grants": ["a.b:read"]}',
    "invalid utf-8": b"\xff\xfe\x00\x01",
    "nan": b'{"version": NaN, "grants": []}',
}
_BAD_ENTRIES = {
    "extra field": entry(extra=1),
    "missing field": {k: v for k, v in entry().items() if k != "method"},
    "scope not a string": entry(scope=7),
    "scope malformed": entry(scope="not a scope"),
    "scope with star": entry(scope="a.b:*"),
    "lifetime once": entry(lifetime="once"),
    "lifetime session": entry(lifetime="session"),
    "lifetime a bool": entry(lifetime=True),
    "lifetime a list": entry(lifetime=["always"]),
    "method unknown": entry(method="telepathy"),
    "method a number": entry(method=3),
    "granted_at naive": entry(granted_at="2026-10-16T09:00:00"),
    "granted_at garbage": entry(granted_at="yesterday"),
    "granted_at a number": entry(granted_at=1760000000),
    "last_used naive": entry(last_used="2026-10-16T09:00:00"),
    "last_used a bool": entry(last_used=False),
}


@pytest.fixture
def audit_log(monkeypatch: pytest.MonkeyPatch) -> AuditRecords:
    return collect_audit(monkeypatch)


def _assert_closed(tmp_path: Path, original: bytes) -> GrantStore:
    """The store has no grants, says why, kept the original bytes, and still works."""
    path = tmp_path / "grants.json"
    store = GrantStore(path, clock=lambda: T0)
    assert store.all() == [] and store.get(Scope.parse("a.b:read")) is None
    assert store.problem is not None and ".bad-" in store.problem
    kept = [p for p in tmp_path.iterdir() if p.name.startswith("grants.json.bad-")]
    assert [p.name for p in kept] == ["grants.json.bad-20261016T090000000000Z"]
    assert kept[0].read_bytes() == original
    assert not path.exists()  # never silently replaced by an empty file
    store.grant(TEAMS_R, "always", "voice")
    assert json.loads(path.read_bytes())["version"] == 1
    assert kept[0].read_bytes() == original  # the evidence survives the next write
    return store


@pytest.mark.parametrize("raw", list(_BAD_FILES.values()), ids=list(_BAD_FILES))
def test_should_set_aside_a_damaged_file_and_start_with_no_grants(
    tmp_path: Path, raw: bytes
) -> None:
    (tmp_path / "grants.json").write_bytes(raw)
    _assert_closed(tmp_path, raw)


@pytest.mark.parametrize("bad", list(_BAD_ENTRIES.values()), ids=list(_BAD_ENTRIES))
def test_should_set_aside_a_file_with_one_bad_grant_even_among_good_ones(
    tmp_path: Path, bad: dict[str, object]
) -> None:
    raw = write_doc(tmp_path / "grants.json", {"version": 1, "grants": [entry("x.y:read"), bad]})
    store = _assert_closed(tmp_path, raw)
    assert store.get(Scope.parse("x.y:read")) is None  # the good entry was not trusted either


def test_should_set_aside_a_file_that_names_a_scope_twice(tmp_path: Path) -> None:
    raw = write_doc(tmp_path / "grants.json", {"version": 1, "grants": [entry(), entry()]})
    _assert_closed(tmp_path, raw)


@pytest.mark.parametrize("lifetime", ["always", "never"])
def test_should_accept_a_valid_hand_written_file(tmp_path: Path, lifetime: str) -> None:
    doc = {
        "version": 1,
        "grants": [entry(lifetime=lifetime, last_used="2026-10-17T10:00:00+00:00")],
    }
    write_doc(tmp_path / "grants.json", doc)
    store = make_store(tmp_path)
    grant = store.get(Scope.parse("a.b:read"))
    assert grant is not None and grant.lifetime == lifetime
    assert grant.last_used == datetime(2026, 10, 17, 10, tzinfo=UTC)
    assert store.problem is None


@posix_only
@pytest.mark.parametrize("target", ["valid", "missing"])
def test_should_not_follow_a_symlinked_grants_file(tmp_path: Path, target: str) -> None:
    elsewhere = tmp_path / "elsewhere" / "grants.json"
    elsewhere.parent.mkdir()
    original = b""
    if target == "valid":
        original = write_doc(elsewhere, {"version": 1, "grants": [entry("a.b:read")]})
    home = tmp_path / "home"
    home.mkdir()
    (home / "grants.json").symlink_to(elsewhere)
    store = GrantStore(home / "grants.json", clock=lambda: T0)
    assert store.all() == [] and store.problem is not None
    kept = home / "grants.json.bad-20261016T090000000000Z"
    assert kept.is_symlink()  # the link itself was renamed, its target never opened
    store.grant(TEAMS_R, "always", "voice")
    assert not (home / "grants.json").is_symlink()
    assert (elsewhere.read_bytes() if target == "valid" else b"") == original  # target untouched
    assert target == "valid" or not elsewhere.exists()


def test_should_audit_the_file_that_was_set_aside(tmp_path: Path, audit_log: AuditRecords) -> None:
    (tmp_path / "grants.json").write_bytes(b"{")
    store = make_store(tmp_path)
    assert audit_log[0][0] == "grants file unusable"
    assert audit_log[0][1]["kept_as"] == "grants.json.bad-20261016T090000000000Z"
    assert store.problem is not None


def test_should_still_start_when_the_audit_of_a_bad_file_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jarvis.consent.store.audit", broken)
    (tmp_path / "grants.json").write_bytes(b"{")
    assert make_store(tmp_path).problem is not None  # no grants, the file is kept: still closed


def test_should_start_closed_when_the_unusable_file_cannot_be_set_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "grants.json").write_bytes(b"{")

    def broken(src: object, dst: object) -> None:
        raise OSError("read-only")

    monkeypatch.setattr("jarvis.consent.store.os.replace", broken)
    store = make_store(tmp_path)  # M3: Jarvis must still start
    assert store.problem is not None and "read-only" in store.problem
    assert store.all() == [] and (tmp_path / "grants.json").read_bytes() == b"{"
