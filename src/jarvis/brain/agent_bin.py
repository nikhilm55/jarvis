"""Locate the claude binary (FR-BRN-11), adapted from beyondMeetings' resolve_agent_binary."""

import os
import shutil
from pathlib import Path

from jarvis.brain.failures import BrainUnavailable

_INSTALL_REMEDY = "Install Claude Code (npm install -g @anthropic-ai/claude-code), then log in."


def _names() -> list[str]:
    """Return the executable names to probe, platform-specific."""
    if os.name == "nt":
        return ["claude.exe", "claude.cmd", "claude"]
    return ["claude"]


def fallback_candidates(home: Path) -> list[Path]:
    """Build the ordered list of candidate paths to probe for the claude binary."""
    candidates: list[Path] = []
    dirs = [
        home / ".local" / "bin",
        home / "bin",
        home / ".npm-global" / "bin",
        home / ".volta" / "bin",
        home / ".bun" / "bin",
        home / ".local" / "share" / "pnpm",
        home / ".local" / "share" / "mise" / "shims",
        home / ".asdf" / "shims",
        home / ".claude" / "local",
    ]
    for directory in dirs:
        for name in _names():
            candidates.append(directory / name)
    for name in _names():
        candidates.extend(
            sorted((home / ".nvm" / "versions" / "node").glob(f"*/bin/{name}"), reverse=True)
        )
    return candidates


def _usable(path: Path) -> bool:
    """Return True if the path is a file the process can execute."""
    return path.is_file() and os.access(path, os.X_OK)


def resolve_claude(configured: str | None = None, *, home: Path | None = None) -> str:
    """Locate the claude executable, honouring an explicit configured path first."""
    if configured and configured.strip():
        explicit = Path(configured).expanduser()
        if _usable(explicit):
            return str(explicit)
        found = shutil.which(configured)
        if found:
            return found
        raise BrainUnavailable(
            f"the configured Claude Code path {configured} does not work",
            ["Fix brain.claude_bin in the Jarvis config, or remove it to search automatically."],
        )
    found = shutil.which("claude")
    if found:
        return found
    for candidate in fallback_candidates(home or Path.home()):
        if _usable(candidate):
            return str(candidate)
    raise BrainUnavailable("Claude Code isn't installed", [_INSTALL_REMEDY])
