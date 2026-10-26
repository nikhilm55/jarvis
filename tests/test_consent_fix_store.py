"""Regression tests for M2 task 3, part C: I2 (R100), M3, M4, M6 and M9 (the grants store)."""

import importlib.util
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from jarvis.config import ConfigError, load_settings
from jarvis.consent.scope import Scope
from jarvis.consent.store import GrantStore, GrantsWriteError
from tests import store_files_rig
from tests.consent_rig import MAIL_R, TEAMS_R, TEAMS_W, make_rig, says
from tests.store_files_rig import posix_only

TEAMS_WRITE = Scope.parse(TEAMS_W)
MAIL_READ = Scope.parse(MAIL_R)
TEAMS_READ = Scope.parse(TEAMS_R)


def on_disk(path: Path) -> dict[str, str]:
    """What a fresh store reads from the file: scope -> lifetime."""
    return {str(g.scope): g.lifetime for g in GrantStore(path).all()}


# --- I2 / R100: one writer at a time, re-read under the lock, apply only your own delta ------


def test_should_keep_both_grants_when_two_stores_share_a_file(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    first, second = GrantStore(path), GrantStore(path)
    first.grant(TEAMS_WRITE, "never", "voice")
    second.grant(MAIL_READ, "always", "voice")
    assert on_disk(path) == {TEAMS_W: "never", MAIL_R: "always"}
    assert second.get(TEAMS_WRITE) is not None  # the second store caught up when it wrote


def test_should_keep_a_never_when_another_store_revokes_something_else(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    first, second = GrantStore(path), GrantStore(path)
    first.grant(MAIL_READ, "always", "voice")
    second.grant(TEAMS_WRITE, "never", "voice")
    assert first.revoke(MAIL_READ)  # first's memory never saw the "never"
    assert on_disk(path) == {TEAMS_W: "never"}


def test_should_lose_no_grant_when_four_threads_write_through_four_stores(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    stores = [GrantStore(path) for _ in range(4)]
    start = threading.Barrier(4)
    errors: list[Exception] = []

    def write(store: GrantStore, worker: int) -> None:
        start.wait()
        for n in range(20):
            try:
                store.grant(Scope.parse(f"files.w{worker}n{n}:read"), "always", "voice")
            except Exception as error:  # a verify error or a lost race
                errors.append(error)

    threads = [threading.Thread(target=write, args=(s, i)) for i, s in enumerate(stores)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(on_disk(path)) == 80


@posix_only
def test_should_keep_the_lock_file_private(tmp_path: Path) -> None:
    old = os.umask(0)  # even a permissive umask must not widen it
    try:
        GrantStore(tmp_path / "grants.json").grant(TEAMS_READ, "always", "voice")
    finally:
        os.umask(old)
    lock = tmp_path / "grants.json.lock"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600


def test_should_not_lock_the_file_between_calls(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    first, second = GrantStore(path), GrantStore(path)
    first.grant(TEAMS_READ, "always", "voice")
    second.grant(MAIL_READ, "always", "voice")
    first.touch(TEAMS_READ)  # would block forever if a call kept the lock
    assert on_disk(path) == {TEAMS_R: "always", MAIL_R: "always"}


# --- M3: a read-only directory does not stop the constructor ----------------------------------


@posix_only
@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="root ignores directory permissions"
)
def test_should_start_empty_and_deny_writes_when_the_unusable_file_cannot_be_set_aside(
    tmp_path: Path,
) -> None:
    (tmp_path / "grants.json").write_bytes(b"{")
    tmp_path.chmod(0o500)  # read and enter, no write: the file cannot be renamed away
    try:
        store = GrantStore(tmp_path / "grants.json")  # must not raise
        assert store.problem is not None and "could not be set aside" in store.problem
        assert store.all() == []
        with pytest.raises(GrantsWriteError):
            store.grant(TEAMS_READ, "always", "voice")
    finally:
        tmp_path.chmod(0o700)
    assert (tmp_path / "grants.json").read_bytes() == b"{"  # the bad file was never overwritten


def test_should_deny_every_write_when_the_unusable_file_cannot_be_set_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "grants.json").write_bytes(b"{")

    def broken(src: object, dst: object) -> None:
        raise OSError("read-only")

    monkeypatch.setattr("jarvis.consent.store.os.replace", broken)
    store = GrantStore(tmp_path / "grants.json")
    assert store.problem is not None and "read-only" in store.problem
    monkeypatch.undo()  # the directory is writable now, but the bad file is still in the way
    with pytest.raises(GrantsWriteError, match="set aside"):
        store.grant(TEAMS_READ, "never", "voice")
    assert (tmp_path / "grants.json").read_bytes() == b"{"


# --- M4: an always/never answer for several scopes is all or nothing ---------------------------


@pytest.mark.parametrize("choice", ["always", "never"])
def test_should_store_none_of_the_scopes_when_the_second_one_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always" if choice == "always" else "never"))
    records: list[str] = []

    def second_fails(source: str, message: str, **fields: object) -> None:
        if message == "grant change":
            records.append(str(fields["scope"]))
            if len(records) == 2:
                raise OSError("audit disk full")

    monkeypatch.setattr("jarvis.consent.store.audit", second_fails)
    assert rig.require(TEAMS_R, MAIL_R) == "denied"
    assert len(records) == 2  # both were attempted: it was the second that failed
    assert rig.store.all() == []
    assert not (tmp_path / "grants.json").exists()


def test_should_store_every_scope_of_one_answer_in_one_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always"))
    writes: list[object] = []
    real = os.replace

    def counted(src: str, dst: str | os.PathLike[str]) -> None:
        writes.append(dst)
        real(src, dst)

    monkeypatch.setattr("jarvis.consent.store.os.replace", counted)
    assert rig.require(TEAMS_R, MAIL_R) == "granted"
    assert len(writes) == 1
    assert on_disk(tmp_path / "grants.json") == {TEAMS_R: "always", MAIL_R: "always"}


# --- M6: consent_folders sources are validated at load -----------------------------------------


@pytest.mark.parametrize("source", ["Bad Source", "files:read", "", "a" * 65, "-x"])
def test_should_name_the_key_of_a_bad_consent_folder_source(tmp_path: Path, source: str) -> None:
    config = tmp_path / "config.toml"
    config.write_text(f'[policy.consent_folders]\n"~/Docs" = "{source}"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_settings(config)
    assert "consent_folders" in str(caught.value) and "~/Docs" in str(caught.value)


def test_should_accept_a_valid_consent_folder_source(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[policy.consent_folders]\n"~/Docs" = "files.docs"\n', encoding="utf-8")
    assert load_settings(config).policy.consent_folders == {"~/Docs": "files.docs"}


# --- M9: the skip condition matches its reason -------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "skipped"), [("linux", False), ("darwin", False), ("win32", True)]
)
def test_should_skip_posix_only_tests_exactly_where_the_reason_says(
    monkeypatch: pytest.MonkeyPatch, platform: str, skipped: bool
) -> None:
    spec = importlib.util.spec_from_file_location("rig_probe", store_files_rig.__file__)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "platform", platform)
    spec.loader.exec_module(probe)
    mark = probe.posix_only.mark
    assert mark.args == (skipped,)
    assert "Windows" in mark.kwargs["reason"] and "Linux" not in mark.kwargs["reason"]
