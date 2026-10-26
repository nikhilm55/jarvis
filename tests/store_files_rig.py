"""More helpers for the GrantStore file tests: hand-made files and collected audit records."""

import json
import sys
from pathlib import Path

import pytest

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file modes and symlinks are not available on Windows"
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
