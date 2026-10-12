"""Tests for jarvis.brain.launch.prepare_launch."""

import json
import stat
from pathlib import Path

from jarvis.brain.launch import prepare_launch
from jarvis.brain.rules import build_rules
from jarvis.config import BrainSettings
from jarvis.paths import runtime_dir


class FakeMcp:
    """Fake MCP client that records config paths and writes a stub file."""

    def __init__(self) -> None:
        self.paths: list[Path] = []

    def write_client_config(self, path: Path) -> None:
        """Record the path and write an empty mcpServers object to it."""
        self.paths.append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")


def value_after(argv: list[str], flag: str) -> str:
    """Return the argv entry immediately following the given flag."""
    return argv[argv.index(flag) + 1]


def test_should_set_binary_and_streaming_flags_when_launching(tmp_path: Path) -> None:
    """argv[0] is the binary and streaming/verbose flags are present."""
    mcp = FakeMcp()
    spec = prepare_launch("/usr/bin/claude", BrainSettings(), mcp, root=tmp_path / "brain")
    argv = spec.argv
    assert argv[0] == "/usr/bin/claude"
    assert "-p" in argv
    assert value_after(argv, "--input-format") == "stream-json"
    assert value_after(argv, "--output-format") == "stream-json"
    assert "--verbose" in argv


def test_should_use_default_model_when_brain_not_configured(tmp_path: Path) -> None:
    """--model defaults to sonnet."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp, root=tmp_path / "brain")
    assert value_after(spec.argv, "--model") == "sonnet"


def test_should_use_configured_model_when_brain_model_set(tmp_path: Path) -> None:
    """--model reflects the configured brain model."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(model="opus"), mcp, root=tmp_path / "brain")
    assert value_after(spec.argv, "--model") == "opus"


def test_should_apply_isolation_flags_when_launching(tmp_path: Path) -> None:
    """Isolation flags are set to empty/strict values."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp, root=tmp_path / "brain")
    argv = spec.argv
    assert value_after(argv, "--setting-sources") == ""
    assert value_after(argv, "--tools") == ""
    assert "--strict-mcp-config" in argv
    assert value_after(argv, "--allowedTools") == "mcp__jarvis__*"
    assert value_after(argv, "--permission-mode") == "dontAsk"
    assert "--no-session-persistence" in argv


def test_should_write_mcp_config_to_recorded_path_when_launching(tmp_path: Path) -> None:
    """--mcp-config points to the path FakeMcp was asked to write."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp, root=tmp_path / "brain")
    config_path = Path(value_after(spec.argv, "--mcp-config"))
    assert mcp.paths == [config_path]
    assert config_path.exists()


def test_should_write_settings_with_deny_list_when_launching(tmp_path: Path) -> None:
    """--settings points to a 0o600 JSON file denying Bash/Write/Read/WebFetch."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp, root=tmp_path / "brain")
    settings_path = Path(value_after(spec.argv, "--settings"))
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    deny = data["permissions"]["deny"]
    assert "Bash" in deny
    assert "Write" in deny
    assert "Read" in deny
    assert "WebFetch" in deny
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600


def test_should_set_system_prompt_to_rules_when_launching(tmp_path: Path) -> None:
    """--system-prompt equals build_rules()."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp, root=tmp_path / "brain")
    assert value_after(spec.argv, "--system-prompt") == build_rules()


def test_should_create_empty_cwd_inside_root_when_launching(tmp_path: Path) -> None:
    """cwd exists, is a directory, is empty, and is inside the given root."""
    mcp = FakeMcp()
    root = tmp_path / "brain"
    spec = prepare_launch("claude", BrainSettings(), mcp, root=root)
    assert spec.cwd.exists()
    assert spec.cwd.is_dir()
    assert list(spec.cwd.iterdir()) == []
    assert spec.cwd.parent == root


def test_should_not_mention_claude_config_dirs_when_launching(tmp_path: Path) -> None:
    """No argv entry mentions .claude."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp, root=tmp_path / "brain")
    assert all(".claude" not in arg for arg in spec.argv)


def test_should_use_runtime_dir_when_root_not_given() -> None:
    """Without root, cwd.parent is runtime_dir() / brain."""
    mcp = FakeMcp()
    spec = prepare_launch("claude", BrainSettings(), mcp)
    assert spec.cwd.parent == runtime_dir() / "brain"


def test_should_rewrite_files_and_keep_cwd_empty_when_called_twice(tmp_path: Path) -> None:
    """A second call rewrites files without error and cwd stays empty."""
    mcp = FakeMcp()
    root = tmp_path / "brain"
    spec1 = prepare_launch("claude", BrainSettings(), mcp, root=root)
    spec2 = prepare_launch("claude", BrainSettings(), mcp, root=root)
    assert spec2.cwd == spec1.cwd
    assert list(spec2.cwd.iterdir()) == []
