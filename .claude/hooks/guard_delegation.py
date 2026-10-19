"""PreToolUse guard for the subagent tool: a dispatch must carry a harness brief.

Wire: event=PreToolUse, matcher="Agent|Task". One job: veto a subagent dispatch whose prompt
lacks the brief's required sections (harness/brief.md), so every delegated task says what
"done" means before work starts. A section counts only outside code fences and HTML comments,
as a markdown heading (levels 1-4) or a bold/plain label at line start (up to 3 spaces of
indent), and only with at least one line of real content: a placeholder (TBD, TODO, ..., <...>)
or an empty checkbox is not content. Read-only helper agents are exempt (harness/README.md).
Every other subagent type, including `fork`, is checked like any other.
"""

from __future__ import annotations

import re

from _hooklib import allow, block, read_payload, tool_input

REQUIRED = ("Goal", "Context", "Constraints", "Done when", "Report", "Local model")
EXEMPT_AGENTS = frozenset({"Explore", "claude-code-guide", "statusline-setup"})
MODE_PREFIX = re.compile(r"(?:\*\*)?mode(?:\*\*)?\s*:\s*(?:\*\*)?\s*", re.I)
MODE = re.compile(r"(?:loop|finisher|review)\b(?!:)|exempt\s*:(.*)", re.I)
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}\1[ \t]*$|\Z)", re.M | re.S)
HEADING = re.compile(r" {0,3}#{1,6}\s")
PLACEHOLDER = re.compile(
    r"\s*(?:[-*+]|\d+[.)])?\s*(?:\[[ xX]?\])?\s*(?:TBD|TODO|N/A|\.{3}|…|<[^<>]*>)?\s*[.:]?\s*",
    re.I,
)


def label(line: str) -> tuple[str, str] | None:
    """The required section this line starts, with any content on the same line."""
    for name in REQUIRED:
        words = r"\s+".join(re.escape(word) for word in name.split())
        forms = (
            (rf"#{{1,4}}[ \t]+(?:\*\*)?{words}\b", False),  # ## Done when  (the rest is a title)
            (rf"\*\*{words}[ \t]*:?[ \t]*\*\*[ \t]*:?", True),  # **Done when:**  or  **Done when**:
            (rf"{words}[ \t]*:", True),  # Done when:
        )
        for form, inline in forms:
            if m := re.match(rf" {{0,3}}{form}", line, re.I):
                return name, line[m.end() :] if inline else ""
    return None


def local_model_mode_ok(content: str) -> bool:
    """True when the Local model section's first content line names a valid mode."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = MODE_PREFIX.sub("", stripped, count=1)
        if m := MODE.match(stripped):
            return m.group(1) is None or len(m.group(1).split()) >= 3
        return False
    return False


def sections(prompt: str) -> dict[str, bool]:
    """Each required section found in the prompt, and whether it has real content."""
    text = FENCE.sub("[code]\n", COMMENT.sub("", prompt))
    found: dict[str, bool] = {}
    current: str | None = None
    for line in text.splitlines():
        start = label(line)
        if start or HEADING.match(line):
            current = start[0] if start else None
        if start:
            found.setdefault(start[0], False)
        content = start[1] if start else line
        if current and content.strip() and not PLACEHOLDER.fullmatch(content):
            found[current] = True
    return found


def _local_model_content(prompt: str) -> str:
    """The Local model section's content, outside code fences and comments."""
    text = FENCE.sub("[code]\n", COMMENT.sub("", prompt))
    lines = text.splitlines()
    current: str | None = None
    collected: list[str] = []
    for line in lines:
        start = label(line)
        if start or HEADING.match(line):
            current = start[0] if start else None
        if current == "Local model":
            collected.append(start[1] if start else line)
    return "\n".join(collected)


def main() -> None:
    inp = tool_input(read_payload())
    if str(inp.get("subagent_type") or "") in EXEMPT_AGENTS:
        allow()
    prompt = inp.get("prompt")
    if not isinstance(prompt, str):
        allow()
    found = sections(prompt)
    missing = [name for name in REQUIRED if name not in found]
    empty = [name for name in REQUIRED if found.get(name) is False]
    if missing or empty:
        problems = f"Missing section(s): {', '.join(missing)}. " if missing else ""
        problems += f"Section(s) with no real content: {', '.join(empty)}. " if empty else ""
        block(
            "This subagent prompt is not a harness brief. "
            + problems
            + "Write each section from harness/brief.md (Goal, Context, Constraints, Done when, "
            "Report, Local model) with real content, not a placeholder, and dispatch again; "
            "see harness/README.md."
        )
    local_model = found.get("Local model")
    if local_model is True:
        content = _local_model_content(prompt)
        if not local_model_mode_ok(content):
            block(
                "Local model section must name a mode: loop, finisher, review or exempt: <reason>"
            )
    allow()


if __name__ == "__main__":
    main()
