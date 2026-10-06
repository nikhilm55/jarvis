"""Shared helpers for Jarvis's Claude Code hooks.

Everything fragile lives here: if Claude Code changes its hook payload or its
blocking mechanism, fix it in this one file and every guard keeps working.
Ported from FiftyfiveTech/claude-base-project-template (lib.sh) to Python so the
same hooks run on Linux and Windows. Stdlib only — hooks must start instantly.

Payload (stdin JSON): {"tool_name", "tool_input": {...}, "hook_event_name", "cwd", ...}
Decisions: we use the structured path (exit 0 + JSON on stdout) so the reason
reaches the agent and it can self-correct. Never mix with exit 2.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, NoReturn

PLACEHOLDER = re.compile(r"your[-_]|placeholder|changeme|xxxx|<[a-z_]+>|\$\{?[A-Z_]+\}?", re.I)

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("an AWS access key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key material", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a GitHub token", re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}")),
    ("a Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("an Anthropic API key", re.compile(r"sk-ant-[0-9A-Za-z_-]{20,}")),
    ("an OpenAI-style API key", re.compile(r"sk-(proj-)?[0-9A-Za-z_-]{20,}")),
    ("a Groq API key", re.compile(r"gsk_[0-9A-Za-z]{20,}")),
    ("a Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    (
        "a hardcoded key/token assignment",
        re.compile(
            r"(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
            r"[\"'\s]*[:=][\"'\s]*[A-Za-z0-9_./+-]{16,}",
            re.I,
        ),
    ),
]

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.[\w-]+)?|[^/]*\.pem|[^/]*\.key|id_(rsa|ed25519|ecdsa|dsa)(\.pub)?)$"
    r"|(^|/)\.(ssh|aws|kube|gnupg)/",
    re.I,
)
TEMPLATE_FILE = re.compile(r"\.(example|sample|template)$", re.I)


def read_payload() -> dict[str, Any]:
    """Read the hook payload once. A malformed payload allows (never wedge the agent)."""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        allow()
    return data if isinstance(data, dict) else {}


def tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input")
    return value if isinstance(value, dict) else {}


def normalise(path: str) -> str:
    """Forward slashes, so one set of patterns covers Windows and POSIX paths on any OS."""
    return path.replace("\\", "/") if path else ""


def written_content(inp: dict[str, Any]) -> str:
    """Write gives content; Edit gives new_string; MultiEdit gives edits[].new_string."""
    parts = [str(inp.get("content") or ""), str(inp.get("new_string") or "")]
    edits = inp.get("edits")
    if isinstance(edits, list):
        parts += [str(e.get("new_string") or "") for e in edits if isinstance(e, dict)]
    return "\n".join(p for p in parts if p)


def secret_kind(text: str) -> str | None:
    """Return a description of the first live-looking secret, ignoring placeholder lines."""
    lines = [line for line in text.splitlines() if not PLACEHOLDER.search(line)]
    scan = "\n".join(lines)
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(scan):
            return kind
    return None


def is_secret_file(path: str) -> bool:
    p = normalise(path)
    return bool(SECRET_FILE.search(p)) and not TEMPLATE_FILE.search(p)


def _decide(decision: str, reason: str) -> NoReturn:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def block(reason: str) -> NoReturn:
    """Veto the tool call and tell the agent why, in plain English."""
    _decide("deny", reason)


def ask(reason: str) -> NoReturn:
    """Require a human to approve this specific call."""
    _decide("ask", reason)


def warn(note: str) -> NoReturn:
    """Allow, but surface a note to the user."""
    print(f"[hook warning] {note}", file=sys.stderr)
    sys.exit(0)


def allow() -> NoReturn:
    sys.exit(0)
