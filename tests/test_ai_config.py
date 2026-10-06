"""The AI-config validator passes on this repo and catches each class of regression."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_ai_config", ROOT / "scripts" / "check_ai_config.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_ai_config"] = module
    spec.loader.exec_module(module)
    return module


checker = load_checker()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for item in [
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        ".mcp.json",
        ".claude",
        "docs",
        "src",
        "tests",
        "scripts",
        ".github",
    ]:
        source = ROOT / item
        target = tmp_path / item
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        elif source.exists():
            shutil.copy2(source, target)
    return tmp_path


def edit_json(path: Path, change: dict[str, object]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(change)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_should_pass_when_run_on_this_repository() -> None:
    assert checker.run(ROOT) == []


def test_should_fail_when_bypass_mode_is_not_disabled(repo: Path) -> None:
    settings = repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["permissions"].pop("disableBypassPermissionsMode")
    settings.write_text(json.dumps(data), encoding="utf-8")
    assert any("disableBypassPermissionsMode" in e for e in checker.run(repo))


def test_should_fail_when_all_project_mcp_servers_are_auto_enabled(repo: Path) -> None:
    edit_json(repo / ".claude" / "settings.json", {"enableAllProjectMcpServers": True})
    assert any("enableAllProjectMcpServers" in e for e in checker.run(repo))


def test_should_fail_when_mcp_server_is_unpinned(repo: Path) -> None:
    edit_json(
        repo / ".mcp.json",
        {
            "mcpServers": {
                "context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp@latest"]}
            }
        },
    )
    errors = checker.run(repo)
    assert any("not pinned" in e for e in errors)
    assert any("latest" in e for e in errors)


def test_should_fail_when_claude_md_does_not_import_agents_md(repo: Path) -> None:
    (repo / "CLAUDE.md").write_text("# Rules copied here\n", encoding="utf-8")
    assert any("@AGENTS.md" in e for e in checker.run(repo))


def test_should_fail_when_agents_md_references_a_missing_path(repo: Path) -> None:
    agents = repo / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8") + "\nSee `docs/does-not-exist.md`.\n", encoding="utf-8"
    )
    assert any("docs/does-not-exist.md" in e for e in checker.run(repo))


def test_should_fail_when_side_effect_skill_can_auto_trigger(repo: Path) -> None:
    skill = repo / ".claude" / "skills" / "open-pr" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace("disable-model-invocation: true\n", ""),
        encoding="utf-8",
    )
    assert any("disable-model-invocation" in e for e in checker.run(repo))


def test_should_fail_when_a_hook_script_is_missing(repo: Path) -> None:
    (repo / ".claude" / "hooks" / "guard_read.py").unlink()
    assert any("guard_read.py" in e for e in checker.run(repo))


def test_should_fail_when_a_doc_link_is_broken(repo: Path) -> None:
    (repo / "docs" / "broken.md").write_text("[x](nowhere.md)\n", encoding="utf-8")
    assert any("broken link" in e for e in checker.run(repo))
