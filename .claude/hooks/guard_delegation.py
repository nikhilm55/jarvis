"""PreToolUse guard for the subagent tool: a dispatch must carry a harness brief.

Wire: event=PreToolUse, matcher="Agent|Task". One job: veto a subagent dispatch whose prompt
lacks the brief's required sections (harness/brief.md), so every delegated task says what
"done" means before work starts. Read-only helper agents are exempt (harness/README.md).
"""

from __future__ import annotations

import re

from _hooklib import allow, block, read_payload, tool_input

REQUIRED = ("Goal", "Context", "Constraints", "Done when", "Report")
EXEMPT_AGENTS = frozenset({"Explore", "claude-code-guide", "statusline-setup"})


def has_section(prompt: str, name: str) -> bool:
    """A section counts as a markdown heading (levels 1-4) or a bold/plain label at line start."""
    words = r"\s+".join(re.escape(word) for word in name.split())
    forms = (
        rf"#{{1,4}}[ \t]+(?:\*\*)?{words}\b",  # ## Done when
        rf"\*\*{words}[ \t]*:?[ \t]*\*\*",  # **Done when:**  or  **Done when**
        rf"{words}[ \t]*:",  # Done when:
    )
    return any(re.search(rf"^[ \t]*{form}", prompt, re.I | re.M) for form in forms)


def main() -> None:
    inp = tool_input(read_payload())
    if str(inp.get("subagent_type") or "") in EXEMPT_AGENTS:
        allow()
    prompt = inp.get("prompt")
    if not isinstance(prompt, str):
        allow()
    missing = [name for name in REQUIRED if not has_section(prompt, name)]
    if missing:
        block(
            "This subagent prompt is not a harness brief. Missing section(s): "
            + ", ".join(missing)
            + ". Rewrite the prompt from harness/brief.md (Goal, Context, Constraints, Done when, "
            "Report) and dispatch again; see harness/README.md."
        )
    allow()


if __name__ == "__main__":
    main()
