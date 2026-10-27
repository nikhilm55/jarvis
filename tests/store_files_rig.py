"""More helpers for the GrantStore file tests: hand-made files and collected audit records."""

import contextlib
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file modes and symlinks are not available on Windows"
)


def is_root() -> bool:
    """True when running as root; Windows has no `geteuid`, so never there."""
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


needs_dir_permissions = pytest.mark.skipif(
    sys.platform == "win32" or is_root(),
    reason="root ignores directory permissions, and Windows has no POSIX directory modes",
)

AuditRecords = list[tuple[str, dict[str, object]]]


def entry(scope: object = "a.b:read", **override: object) -> dict[str, object]:
    base: dict[str, object] = {
        "scope": scope,
        "lifetime": "always",
        "method": "voice",
        "granted_at": "2026-10-16T09:00:00Z",
        "last_used": None,
    }
    return base | override


def write_doc(path: Path, document: object) -> bytes:
    raw = json.dumps(document).encode("utf-8")
    path.write_bytes(raw)
    return raw


def tmp_files(tmp_path: Path) -> list[str]:
    return [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def collect_audit(monkeypatch: pytest.MonkeyPatch) -> AuditRecords:
    """Collect the store's audit records instead of writing them."""
    records: AuditRecords = []
    monkeypatch.setattr(
        "jarvis.consent.store.audit", lambda src, msg, **kw: records.append((msg, kw))
    )
    return records


@contextlib.contextmanager
def hold_lock(grants: Path) -> Iterator[None]:
    """Hold the grants flock on a second descriptor, as another process would (POSIX only)."""
    import fcntl  # noqa: PLC0415 - not available on Windows

    fd = os.open(f"{grants}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
