"""Stop gate: before the agent says "done", lint, type-check and test any changed code.

Wire: event=Stop. If Python files changed and a check fails, block the stop and
hand the agent the trimmed failure so it fixes it first. Skips when nothing
changed, and never loops (respects stop_hook_active).
"""

from __future__ import annotations

import json
import subprocess
import sys

from _hooklib import read_payload

CHECKS: list[tuple[str, list[str]]] = [
    ("ruff", ["uv", "run", "--quiet", "ruff", "check", "--quiet", "."]),
    ("mypy", ["uv", "run", "--quiet", "mypy", "--no-error-summary"]),
    (
        "pytest",
        ["uv", "run", "--quiet", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
    ),
]
TAIL_LINES = 30


def changed_python_files(cwd: str | None) -> bool:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd or None,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.rstrip().endswith((".py", ".toml")) for line in out.stdout.splitlines())


def main() -> None:
    payload = read_payload()
    cwd = payload.get("cwd")
    if payload.get("stop_hook_active") or not changed_python_files(cwd):
        sys.exit(0)

    for name, cmd in CHECKS:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd or None,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[stop_verify] could not run {name}: {exc}", file=sys.stderr)
            sys.exit(0)
        if result.returncode != 0:
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-TAIL_LINES:])
            reason = f"{name} failed — fix this before finishing:\n{tail}"
            print(json.dumps({"decision": "block", "reason": reason}))
            sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
