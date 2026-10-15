"""Tests for jarvis.brain.stderr_log."""

import os
import stat

import pytest

from jarvis.brain.stderr_log import KEEP, MAX_BYTES, open_stderr_log, stderr_log_path
from jarvis.paths import data_dir


def test_should_return_expected_path_when_jarvis_home_is_set() -> None:
    path = stderr_log_path()
    assert path == data_dir() / "logs" / "brain-stderr.log"


def test_should_create_nothing_on_disk_when_called() -> None:
    stderr_log_path()
    assert not stderr_log_path().parent.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_should_create_file_with_mode_0600_when_opening() -> None:
    fd = open_stderr_log()
    try:
        mode = stat.S_IMODE(os.fstat(fd).st_mode)
        assert mode == 0o600
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_should_create_logs_dir_with_mode_0700_when_opening() -> None:
    fd = open_stderr_log()
    try:
        logs_dir = stderr_log_path().parent
        mode = stat.S_IMODE(logs_dir.stat().st_mode)
        assert mode == 0o700
    finally:
        os.close(fd)


def test_should_append_to_existing_file_when_small() -> None:
    log_path = stderr_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = b"existing content"
    log_path.write_bytes(existing)

    fd = open_stderr_log()
    try:
        os.write(fd, b"new line")
    finally:
        os.close(fd)

    assert log_path.read_bytes() == existing + b"new line"
    assert not (log_path.parent / "brain-stderr.log.1").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_should_rotate_when_log_exceeds_max_bytes() -> None:
    log_path = stderr_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    old_bytes = b"x" * (MAX_BYTES + 1)
    log_path.write_bytes(old_bytes)

    os.close(open_stderr_log())

    assert log_path.read_bytes() == b""
    backup = log_path.parent / "brain-stderr.log.1"
    assert backup.read_bytes() == old_bytes
    assert backup.stat().st_size == MAX_BYTES + 1
    backup_mode = stat.S_IMODE(backup.stat().st_mode)
    assert backup_mode == 0o600


def test_should_not_rotate_when_log_is_exactly_max_bytes() -> None:
    log_path = stderr_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    old_bytes = b"y" * MAX_BYTES
    log_path.write_bytes(old_bytes)

    os.close(open_stderr_log())

    assert log_path.read_bytes() == old_bytes
    assert not (log_path.parent / "brain-stderr.log.1").exists()


def test_should_keep_at_most_keep_backups_when_rotating_repeatedly() -> None:
    log_path = stderr_log_path()
    os.close(open_stderr_log())

    markers = [b"a", b"b", b"c", b"d", b"e"]
    for marker in markers:
        log_path.write_bytes(marker * (MAX_BYTES + 1))
        os.close(open_stderr_log())

    for i in range(1, KEEP + 1):
        backup = log_path.parent / f"brain-stderr.log.{i}"
        assert backup.exists()
        content = backup.read_bytes()
        assert content[0] == markers[-i][0]

    assert not (log_path.parent / "brain-stderr.log.4").exists()
