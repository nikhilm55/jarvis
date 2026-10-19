"""Writing the grants: private, atomic, verified, and last-used stamped (R87)."""

import os
import stat
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import IO, Any

import pytest

from jarvis.consent.store import GrantStore, GrantsWriteError
from tests.store_files_rig import entry, posix_only, tmp_files, write_doc
from tests.store_rig import (
    SLACK_W,
    T0,
    TEAMS_R,
    TEAMS_W,
    make_store,
)

# --- writing: private, atomic, verified ---------------------------------------------------


@posix_only
def test_should_write_the_file_with_mode_0600(tmp_path: Path) -> None:
    make_store(tmp_path).grant(TEAMS_R, "always", "voice")
    assert stat.S_IMODE(os.stat(tmp_path / "grants.json").st_mode) == 0o600


@posix_only
def test_should_tighten_a_0644_file_on_the_next_write(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    write_doc(path, {"version": 1, "grants": [entry()]})
    path.chmod(0o644)
    store = make_store(tmp_path)
    assert len(store.all()) == 1  # a loose file is still read
    store.grant(TEAMS_R, "always", "voice")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_should_leave_no_temp_file_after_a_write(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    store.touch(TEAMS_R)
    assert tmp_files(tmp_path) == []


def test_should_create_the_parent_directory(tmp_path: Path) -> None:
    store = GrantStore(tmp_path / "deep" / "er" / "grants.json", clock=lambda: T0)
    store.grant(TEAMS_R, "always", "voice")
    assert (tmp_path / "deep" / "er" / "grants.json").is_file()


def test_should_keep_the_old_file_and_state_when_the_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    before = (tmp_path / "grants.json").read_bytes()

    def broken(src: object, dst: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr("jarvis.consent.store.os.replace", broken)
    with pytest.raises(GrantsWriteError, match="disk gone"):
        store.grant(TEAMS_W, "always", "voice")
    assert (tmp_path / "grants.json").read_bytes() == before
    assert store.get(TEAMS_W) is None and store.get(TEAMS_R) is not None  # memory unchanged too
    assert tmp_files(tmp_path) == []


def test_should_clean_up_when_the_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr("jarvis.consent.store.os.fsync", broken)
    store = make_store(tmp_path)
    with pytest.raises(GrantsWriteError):
        store.grant(TEAMS_R, "always", "voice")
    assert not (tmp_path / "grants.json").exists() and tmp_files(tmp_path) == []
    assert store.all() == []


class _Liar:
    """A file handle that writes something other than what it was given."""

    def __init__(self, inner: IO[str]) -> None:
        self._inner = inner

    def __enter__(self) -> "_Liar":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._inner.close()

    def write(self, text: str) -> int:
        return self._inner.write(text.replace("always", "never"))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_should_refuse_to_replace_the_file_with_data_that_does_not_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    before = (tmp_path / "grants.json").read_bytes()
    real = os.fdopen
    monkeypatch.setattr(
        "jarvis.consent.store.os.fdopen", lambda fd, mode, **kw: _Liar(real(fd, mode, **kw))
    )
    with pytest.raises(GrantsWriteError, match="not what was meant"):
        store.grant(TEAMS_W, "always", "voice")
    assert (tmp_path / "grants.json").read_bytes() == before
    assert store.get(TEAMS_W) is None
    assert tmp_files(tmp_path) == []


def test_should_not_trust_the_state_when_the_file_on_disk_fails_the_final_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    real = GrantStore._verify
    calls: list[Path] = []

    def verify(self: GrantStore, path: Path, intended: dict[str, object]) -> None:
        calls.append(path)
        if path == tmp_path / "grants.json":  # the second check, after the replace
            raise ValueError("what was written is not what was meant to be written")
        real(self, path, intended)

    monkeypatch.setattr(GrantStore, "_verify", verify)
    with pytest.raises(GrantsWriteError):
        store.grant(TEAMS_R, "always", "voice")
    assert len(calls) == 2
    assert store.get(TEAMS_R) is None  # never trust a write that did not verify


def test_should_record_last_used_for_a_known_scope_and_ignore_an_unknown_one(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.grant(TEAMS_R, "always", "voice")
    used = T0 + timedelta(hours=5)
    later = GrantStore(tmp_path / "grants.json", clock=lambda: used)
    later.touch(TEAMS_R)
    later.touch(SLACK_W)
    grant = GrantStore(tmp_path / "grants.json").get(TEAMS_R)
    assert grant is not None and grant.last_used == used
    assert later.get(SLACK_W) is None
