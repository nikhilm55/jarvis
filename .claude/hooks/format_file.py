"""PostToolUse reactor: format and auto-fix Python files after the agent writes them.

Wire: event=PostToolUse, matcher="Write|Edit|MultiEdit". Never blocks, and is
idempotent — running it twice changes nothing the second time.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path

from _hooklib import allow, read_payload, tool_input


def run(*args: str) -> None:
    # A formatter problem must never block the agent.
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(args, capture_output=True, timeout=30, check=False)


def main() -> None:
    path = str(tool_input(read_payload()).get("file_path") or "")
    if path.endswith(".py") and Path(path).is_file() and shutil.which("uv"):
        run("uv", "run", "--quiet", "ruff", "check", "--fix", "--quiet", path)
        run("uv", "run", "--quiet", "ruff", "format", "--quiet", path)
    allow()


if __name__ == "__main__":
    main()
