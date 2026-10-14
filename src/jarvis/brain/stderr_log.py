"""Rotate and expose a size-capped stderr log fd for the brain child process."""

import os
from pathlib import Path

from jarvis.paths import data_dir, ensure

__all__ = ["KEEP", "MAX_BYTES", "open_stderr_log", "stderr_log_path"]

MAX_BYTES = 1024 * 1024
KEEP = 3


def stderr_log_path() -> Path:
    """Return the canonical brain stderr log path without touching disk."""
    return data_dir() / "logs" / "brain-stderr.log"


def open_stderr_log() -> int:
    """Rotate the log if oversized and return a writable O_APPEND fd (0o600)."""
    path = stderr_log_path()
    log_dir = path.parent
    ensure(log_dir)
    os.chmod(log_dir, 0o700)

    if path.exists() and path.stat().st_size > MAX_BYTES:
        _rotate(path)

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(path, 0o600)
    return fd


def _rotate(path: Path) -> None:
    """Shift each backup up one slot (the oldest is dropped) and move the live log to .1."""
    path.chmod(0o600)  # a log made by an older run keeps no looser bits in its backup
    slots = [path] + [path.with_name(f"{path.name}.{n}") for n in range(1, KEEP + 1)]
    slots[-1].unlink(missing_ok=True)
    for older, newer in zip(reversed(slots[:-1]), reversed(slots[1:]), strict=True):
        if older.exists():
            older.replace(newer)
