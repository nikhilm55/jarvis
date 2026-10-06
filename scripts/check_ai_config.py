"""Validate the repository's AI agent configuration. Runs in pre-commit and CI.

Checks that instruction files stay lean and linked, settings keep their safety
properties, MCP servers are pinned and inventoried, skills are well-formed, and
the docs that agents rely on resolve. Exit 1 with one line per problem.

Usage: uv run python scripts/check_ai_config.py [repo_root]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

MAX_AGENTS_LINES = 200
MAX_ALWAYS_LOADED_LINES = 300
MAX_SKILL_LINES = 500
MAX_DESCRIPTION_CHARS = 1024
MAX_OPEN_QUESTIONS = 10
PINNED = re.compile(r"@\d+\.\d+\.\d+$")
SIDE_EFFECT_TOOLS = re.compile(r"Bash\((git push|gh pr create|gh release|uv publish)")
MD_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|mailto:|#)([^)#\s]+)")
REPO_PATH = re.compile(r"`((?:src|tests|docs|scripts|\.claude|\.github)/[\w./-]*)`")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    block = text[4 : text.find("\n---", 4)]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            fields[key.strip()] = value.strip().strip('"')
    return fields


def check_instructions(root: Path) -> list[str]:
    errors: list[str] = []
    agents, claude = root / "AGENTS.md", root / "CLAUDE.md"
    if not agents.is_file():
        return ["AGENTS.md is missing (single source of agent instructions)"]
    agent_lines = len(read(agents).splitlines())
    if agent_lines > MAX_AGENTS_LINES:
        errors.append(f"AGENTS.md has {agent_lines} lines (max {MAX_AGENTS_LINES})")
    if not claude.is_file():
        errors.append("CLAUDE.md is missing")
    else:
        claude_text = read(claude)
        if claude_text.splitlines()[:1] != ["@AGENTS.md"]:
            errors.append("CLAUDE.md must start with '@AGENTS.md' (single source of truth)")
        total = agent_lines + len(claude_text.splitlines())
        if total > MAX_ALWAYS_LOADED_LINES:
            errors.append(
                f"always-loaded instructions are {total} lines (max {MAX_ALWAYS_LOADED_LINES})"
            )
    for match in REPO_PATH.finditer(read(agents)):
        rel = match.group(1).rstrip("/").split("::")[0]
        if not (root / rel).exists():
            errors.append(f"AGENTS.md references missing path: {rel}")
    return errors


def _hook_commands(settings: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            commands += [h.get("command", "") for h in group.get("hooks", [])]
    return commands


def check_settings(root: Path) -> list[str]:
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        return [".claude/settings.json is missing"]
    try:
        settings = json.loads(read(path))
    except json.JSONDecodeError as exc:
        return [f".claude/settings.json is not valid JSON: {exc}"]
    errors: list[str] = []
    perms = settings.get("permissions", {})
    if perms.get("disableBypassPermissionsMode") != "disable":
        errors.append("settings: permissions.disableBypassPermissionsMode must be 'disable'")
    if perms.get("defaultMode") in {"bypassPermissions", "dontAsk"}:
        errors.append(f"settings: defaultMode '{perms['defaultMode']}' is not allowed")
    if settings.get("enableAllProjectMcpServers"):
        errors.append(
            "settings: enableAllProjectMcpServers must not be true (approve servers by name)"
        )
    if any(rule in ("Bash(*)", "Bash", "mcp__*") for rule in perms.get("allow", [])):
        errors.append("settings: wildcard allow rule found (Bash(*) / mcp__*)")
    if "Read(./.env)" not in perms.get("deny", []):
        errors.append("settings: deny rules must include Read(./.env)")
    if not settings.get("sandbox", {}).get("enabled"):
        errors.append("settings: sandbox.enabled must be true")
    for command in _hook_commands(settings):
        for script in re.findall(r"\$CLAUDE_PROJECT_DIR/([\w./-]+)", command):
            if not (root / script).is_file():
                errors.append(f"settings: hook script not found: {script}")
    return errors


def check_mcp(root: Path) -> list[str]:
    path = root / ".mcp.json"
    if not path.is_file():
        return []
    errors: list[str] = []
    servers: dict[str, Any] = json.loads(read(path)).get("mcpServers", {})
    settings_path = root / ".claude" / "settings.json"
    enabled = (
        json.loads(read(settings_path)).get("enabledMcpjsonServers", [])
        if settings_path.is_file()
        else []
    )
    inventory_path = root / "docs" / "ai" / "mcp.md"
    inventory = read(inventory_path) if inventory_path.is_file() else ""
    for name, server in servers.items():
        args = [str(a) for a in server.get("args", [])]
        packages = [a for a in args if not a.startswith("-")]
        if server.get("command") in {"npx", "uvx", "pipx"} and not any(
            PINNED.search(p) for p in packages
        ):
            errors.append(f".mcp.json: server '{name}' is not pinned to an exact version")
        if any("latest" in a for a in args):
            errors.append(f".mcp.json: server '{name}' uses 'latest'")
        url = str(server.get("url", ""))
        if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
            errors.append(f".mcp.json: server '{name}' uses plain http for a remote URL")
        if re.search(r"(sk-|gh[pousr]_|xox[baprs]-|AKIA)[\w-]{8,}", json.dumps(server)):
            errors.append(f".mcp.json: server '{name}' contains a literal credential")
        if f"`{name}`" not in inventory:
            errors.append(f"docs/ai/mcp.md: server '{name}' is not in the inventory")
        if name not in enabled:
            errors.append(f"settings: MCP server '{name}' is not listed in enabledMcpjsonServers")
    return errors


def check_skills(root: Path) -> list[str]:
    errors: list[str] = []
    for skill in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
        rel = skill.relative_to(root).as_posix()
        text = read(skill)
        meta = frontmatter(text)
        if meta.get("name") != skill.parent.name:
            errors.append(f"{rel}: frontmatter name must equal the folder name")
        description = meta.get("description", "")
        if not description or len(description) > MAX_DESCRIPTION_CHARS:
            errors.append(f"{rel}: description missing or over {MAX_DESCRIPTION_CHARS} chars")
        if not re.search(r"\buse (when|before|for|after)\b", description, re.I):
            errors.append(f"{rel}: description must say when to use it ('Use when/before …')")
        if "allowed-tools" not in meta:
            errors.append(f"{rel}: allowed-tools must scope the skill's tools")
        if len(text.splitlines()) > MAX_SKILL_LINES:
            errors.append(f"{rel}: over {MAX_SKILL_LINES} lines")
        if (
            not re.search(r"^## (\d+\.\s*)?Verify", text, re.M)
            and meta.get("name") != "python-practices"
        ):
            errors.append(f"{rel}: must end with a '## Verify' step")
        if (
            SIDE_EFFECT_TOOLS.search(meta.get("allowed-tools", ""))
            and meta.get("disable-model-invocation") != "true"
        ):
            errors.append(f"{rel}: has side effects, so it must set disable-model-invocation: true")
    return errors


def check_docs(root: Path) -> list[str]:
    errors: list[str] = []
    docs = [
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / "README.md",
        *sorted((root / "docs").rglob("*.md")),
    ]
    for doc in (d for d in docs if d.is_file() and "design" not in d.parts):
        for target in MD_LINK.findall(read(doc)):
            if not (doc.parent / target).resolve().exists():
                errors.append(f"{doc.relative_to(root).as_posix()}: broken link -> {target}")
    oq_path = root / "docs" / "open-questions.md"
    if oq_path.is_file():
        entries = re.split(r"^## (?=OQ-\d{3})", read(oq_path), flags=re.M)[1:]
        open_entries = [e for e in entries if re.search(r"\*\*Status:\*\* open", e)]
        if len(open_entries) >= MAX_OPEN_QUESTIONS:
            errors.append(
                f"docs/open-questions.md: {len(open_entries)} open (keep < {MAX_OPEN_QUESTIONS})"
            )
        errors += [
            f"docs/open-questions.md: {e.split(' ', 1)[0]} has no Owner"
            for e in entries
            if "**Owner:**" not in e
        ]
    numbers = [p.name[:4] for p in (root / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")]
    errors += [
        f"docs/adr: duplicate ADR number {n}" for n in {n for n in numbers if numbers.count(n) > 1}
    ]
    return errors


def run(root: Path) -> list[str]:
    return [
        *check_instructions(root),
        *check_settings(root),
        *check_mcp(root),
        *check_skills(root),
        *check_docs(root),
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    errors = run(root)
    for error in errors:
        print(f"✗ {error}")
    if errors:
        print(f"{len(errors)} AI-config problem(s).")
        return 1
    print("✓ AI config OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
