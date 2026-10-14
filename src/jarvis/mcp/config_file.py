"""Atomic, owner-only JSON file writes for secrets such as the MCP client config."""

import json
import os
import secrets
from collections.abc import Mapping
from pathlib import Path


def write_private_json(path: Path, data: Mapping[str, object]) -> None:
    """Atomically write `data` as JSON to `path`, created mode 0600 (never wider, even briefly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
