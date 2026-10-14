"""Isolated claude command line and files for the brain session (R45, FR-BRN-02)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jarvis.brain.rules import build_rules
from jarvis.config import BrainSettings
from jarvis.mcp.config_file import write_private_json
from jarvis.paths import ensure, runtime_dir

__all__ = ["LaunchSpec", "McpConfigWriter", "prepare_launch"]

_DENIED_BUILTINS = (
    "Bash",
    "Edit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "TodoWrite",
    "Skill",
)


class McpConfigWriter(Protocol):
    """Protocol for writing the MCP client configuration file."""

    def write_client_config(self, path: Path) -> None:
        """Write the --mcp-config JSON file with mode 0600."""


@dataclass(frozen=True)
class LaunchSpec:
    """The fully isolated command line and working directory for the brain."""

    argv: list[str]
    cwd: Path


def prepare_launch(
    claude_bin: str,
    brain: BrainSettings,
    mcp: McpConfigWriter,
    root: Path | None = None,
) -> LaunchSpec:
    """Build the isolated command line and files for the headless brain session."""
    root = ensure(root or runtime_dir() / "brain")
    cwd = ensure(root / "cwd")
    mcp_path = root / "mcp.json"
    settings_path = root / "settings.json"

    mcp.write_client_config(mcp_path)
    settings = {"permissions": {"deny": list(_DENIED_BUILTINS)}, "disableAllHooks": True}
    write_private_json(settings_path, settings)

    # setting-sources empty = no user/project/local settings or hooks
    # strict-mcp-config = only Jarvis's server
    # tools "" = no built-in tools
    # allowedTools = never block on a permission prompt
    # dontAsk = anything not allowed is denied, never prompted
    # system-prompt replaces the default coding prompt (cheaper, no coding persona)
    # no-session-persistence = nothing written under ~/.claude
    argv = [
        claude_bin,
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        brain.model,
        "--setting-sources",
        "",
        "--settings",
        str(settings_path),
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_path),
        "--tools",
        "",
        "--allowedTools",
        "mcp__jarvis__*",
        "--permission-mode",
        "dontAsk",
        "--system-prompt",
        build_rules(),
        "--no-session-persistence",
    ]
    return LaunchSpec(argv=argv, cwd=cwd)
