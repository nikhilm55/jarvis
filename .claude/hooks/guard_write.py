"""PreToolUse guard for Write/Edit/MultiEdit: protect secrets, generated files and agent config.

Wire: event=PreToolUse, matcher="Write|Edit|MultiEdit". One job: inspect the
target path and the content about to be written.
"""

from __future__ import annotations

import re

from _hooklib import (
    allow,
    ask,
    block,
    is_secret_file,
    normalise,
    read_payload,
    secret_kind,
    tool_input,
    written_content,
)

GENERATED = re.compile(
    r"(^|/)(\.git|\.venv|venv|dist|build|__pycache__|node_modules|\.mypy_cache|\.ruff_cache)/"
)
LOCKFILES = {"uv.lock", "poetry.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
# Changes here alter how agents behave or what CI enforces: a human approves each one.
APPROVAL_GATED = re.compile(
    r"(^|/)(AGENTS\.md|CLAUDE\.md|\.mcp\.json|\.pre-commit-config\.yaml|CODEOWNERS)$"
    r"|(^|/)\.claude/(settings\.json|hooks/)|(^|/)\.github/workflows/"
)
TEMPLATE = re.compile(r"\.(example|sample|template)$", re.I)


def main() -> None:
    inp = tool_input(read_payload())
    path = normalise(str(inp.get("file_path") or ""))
    if not path:
        allow()
    name = path.rsplit("/", 1)[-1]

    if is_secret_file(path):
        block(
            f"{path} holds real secrets. Edit the .example template instead; humans manage the real file."
        )
    if GENERATED.search(path):
        block(f"{path} is generated or VCS-internal. Change the source, not the output.")
    if name in LOCKFILES:
        block(f"{name} is a lockfile. Run `uv add`/`uv lock` and let uv regenerate it.")

    content = written_content(inp)
    if content and not TEMPLATE.search(name):
        kind = secret_kind(content)
        if kind:
            block(
                f"That looks like {kind} in {path}. Never write credentials to files; read them from the environment or keyring."
            )

    if APPROVAL_GATED.search(path):
        ask(f"{path} is agent/CI configuration. A human must approve this change.")
    allow()


if __name__ == "__main__":
    main()
