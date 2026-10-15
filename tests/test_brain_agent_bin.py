"""Tests for jarvis.brain.agent_bin and jarvis.brain.failures."""

import sys
from pathlib import Path

import pytest

from jarvis.brain.agent_bin import resolve_claude
from jarvis.brain.failures import BrainUnavailable, failed_response
from jarvis.contract import FALLBACK_SPOKEN, FinalResponse


def _make_executable(path: Path) -> None:
    """Create an executable shell script at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


def _make_non_executable(path: Path) -> None:
    """Create a non-executable file at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o644)


def test_should_return_configured_path_when_usable_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A usable configured file wins over PATH lookup."""
    fake_bin = tmp_path / "myclaude"
    _make_executable(fake_bin)
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda _name: None,
    )
    result = resolve_claude(str(fake_bin), home=tmp_path)
    assert result == str(fake_bin)


def test_should_fall_through_to_path_when_configured_is_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank configured string is ignored and PATH is consulted."""
    path_hit = tmp_path / "claude_on_path"
    _make_executable(path_hit)
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda name: str(path_hit) if name == "claude" else None,
    )
    result = resolve_claude("   ", home=tmp_path)
    assert result == str(path_hit)


def test_should_raise_brain_unavailable_naming_path_when_configured_is_bad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad configured path raises BrainUnavailable mentioning it."""
    bad = tmp_path / "does_not_exist"
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(BrainUnavailable) as exc_info:
        resolve_claude(str(bad), home=tmp_path)
    assert str(bad) in exc_info.value.why


def test_should_return_path_hit_when_configured_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When configured is None, shutil.which('claude') result is returned."""
    path_hit = tmp_path / "claude_on_path"
    _make_executable(path_hit)
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda name: str(path_hit) if name == "claude" else None,
    )
    result = resolve_claude(None, home=tmp_path)
    assert result == str(path_hit)


def test_should_find_local_bin_fallback_when_path_has_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """~/.local/bin/claude is found when PATH lookup fails."""
    local_bin = tmp_path / ".local" / "bin" / "claude"
    _make_executable(local_bin)
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda _name: None,
    )
    result = resolve_claude(None, home=tmp_path)
    assert result == str(local_bin)


def test_should_pick_highest_nvm_version_dir_when_multiple_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The newest-looking nvm version directory is preferred."""
    nvm_base = tmp_path / ".nvm" / "versions" / "node"
    v18 = nvm_base / "v18.0.0" / "bin" / "claude"
    v22 = nvm_base / "v22.1.0" / "bin" / "claude"
    _make_executable(v18)
    _make_executable(v22)
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda _name: None,
    )
    result = resolve_claude(None, home=tmp_path)
    assert result == str(v22)


@pytest.mark.skipif(sys.platform != "linux", reason="the executable bit is POSIX-only")
def test_should_skip_non_executable_file_when_scanning_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-executable file in a fallback location is skipped."""
    local_bin = tmp_path / ".local" / "bin" / "claude"
    _make_non_executable(local_bin)
    npm_global = tmp_path / ".npm-global" / "bin" / "claude"
    _make_executable(npm_global)
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda _name: None,
    )
    result = resolve_claude(None, home=tmp_path)
    assert result == str(npm_global)


def test_should_raise_brain_unavailable_with_npm_remedy_when_nothing_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no candidate exists, BrainUnavailable mentions npm install."""
    monkeypatch.setattr(
        "jarvis.brain.agent_bin.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(BrainUnavailable) as exc_info:
        resolve_claude(None, home=tmp_path)
    assert exc_info.value.code == "BRAIN_UNAVAILABLE"
    assert any("npm" in item for item in exc_info.value.remedy)


def test_should_return_failed_final_response_when_to_response_called() -> None:
    """BrainUnavailable.to_response() yields a failed FinalResponse with correct fields."""
    err = BrainUnavailable(
        why="No claude binary found in PATH or fallback locations",
        remedy=["Run npm install -g @anthropic-ai/claude-code"],
    )
    response = err.to_response()
    assert isinstance(response, FinalResponse)
    assert response.status == "failed"
    assert response.error is not None
    assert response.error.code == "BRAIN_UNAVAILABLE"
    assert response.error.remedy == ["Run npm install -g @anthropic-ai/claude-code"]
    assert response.spoken.startswith("My AI brain isn't available")
    assert "No claude binary found in PATH or fallback locations" in response.spoken


def test_should_use_fallback_spoken_when_spoken_sanitises_to_empty() -> None:
    """failed_response uses FALLBACK_SPOKEN when the given spoken sanitises to nothing."""
    response = failed_response(
        code="BRAIN_UNAVAILABLE",
        what="Claude Code isn't installed",
        why="No claude binary found",
        remedy=["Run npm install -g @anthropic-ai/claude-code"],
        spoken="```x```",
    )
    assert response.status == "failed"
    assert response.spoken == FALLBACK_SPOKEN
