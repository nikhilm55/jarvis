"""PreToolUse guard for the Bash tool: veto commands that are destructive or bypass review.

Wire: event=PreToolUse, matcher="Bash". One job: inspect the proposed command.
Every veto explains itself so the agent corrects course instead of retrying.
"""

from __future__ import annotations

import re
import subprocess

from _hooklib import allow, block, is_secret_file, read_payload, secret_kind, tool_input, warn

PROTECTED_BRANCHES = {"main", "master"}

RM_RECURSIVE_FORCE = re.compile(
    r"\brm\s+(-\w*r\w*f|-\w*f\w*r|-r\s+-f|-f\s+-r|--recursive\s+--force)"
)
RM_SENSITIVE_TARGET = re.compile(
    r"(^|\s)(/|~|\*|\.\.?)(\s|$)|\.git(\s|/|$)|\.env|\.pem|\.key|id_rsa|secrets?|src(\s|/|$)|docs(\s|/|$)"
)
PS_RECURSIVE_DELETE = re.compile(r"Remove-Item\b.*-Recurse\b", re.I)
FORCE_PUSH = re.compile(r"\bgit\s+push\b.*(\s--force(\s|$)|\s-f(\s|$)|\s\+\S)")
NO_VERIFY = re.compile(r"\bgit\b.*\s--no-verify\b|\bgit\s+commit\b.*\s-n(\s|$)")
PIPE_TO_SHELL = re.compile(
    r"(curl|wget)\s.*\|\s*(sudo\s+)?(ba|z)?sh\b|\b(iex|Invoke-Expression)\b", re.I
)
DUMP_SECRET = re.compile(
    r"(^|[;&|\s])(cat|less|more|head|tail|strings|bat|tac|xxd|od|type|gc|Get-Content)\s+([^;&|]+)"
)
DISK_WIPE = re.compile(r"\b(mkfs(\.\w+)?|diskpart|format\s+[a-z]:)|\bdd\s+if=", re.I)
SQL_DESTRUCTIVE = re.compile(r"\b(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)\b", re.I)
SUDO = re.compile(r"(^|[;&|]\s*)sudo\s")
GH_MERGE_OR_APPROVE = re.compile(
    r"\bgh\s+pr\s+(merge|review\b.*--approve)|\bgh\s+(repo\s+delete|release\s+(create|delete))"
)
PIP_INSTALL = re.compile(r"(^|[;&|]\s*)(uv\s+)?pip3?\s+install\b")
GIT_COMMIT = re.compile(r"\bgit\s+commit\b")
GIT_PUSH = re.compile(r"\bgit\s+push\b(.*)")


def current_branch(cwd: str | None) -> str:
    try:
        out = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd or None,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip()


def check(cmd: str, cwd: str | None) -> None:  # noqa: PLR0912 — a flat list of rules reads best
    if RM_RECURSIVE_FORCE.search(cmd) and RM_SENSITIVE_TARGET.search(cmd):
        block(
            f"Recursive force-delete of a sensitive or repo-wide path: '{cmd}'. Delete specific files instead, or ask the human to run it."
        )
    if PS_RECURSIVE_DELETE.search(cmd) and "-Force" in cmd:
        block(
            f"Recursive forced Remove-Item: '{cmd}'. Delete specific files instead, or ask the human."
        )
    if DISK_WIPE.search(cmd):
        block(f"Disk-level destructive command: '{cmd}'. Never run this from the agent.")
    if SQL_DESTRUCTIVE.search(cmd):
        block(f"Destructive SQL (DROP/TRUNCATE): '{cmd}'. A human must run this.")
    if FORCE_PUSH.search(cmd):
        block(
            f"Force-push rewrites shared history: '{cmd}'. Use --force-with-lease on your own branch only."
        )
    if NO_VERIFY.search(cmd):
        block(f"--no-verify skips the safety hooks: '{cmd}'. Fix what the hook reports instead.")
    if PIPE_TO_SHELL.search(cmd):
        block(
            f"Running a downloaded script unreviewed: '{cmd}'. Download it, read it, then ask the human."
        )
    if SUDO.search(cmd):
        block(
            f"sudo from the agent is not allowed: '{cmd}'. Tell the human the exact command and why."
        )
    if GH_MERGE_OR_APPROVE.search(cmd):
        block(
            f"Merging, approving, releasing or deleting repos is a human decision: '{cmd}'. Open the PR and stop."
        )
    if PIP_INSTALL.search(cmd):
        block(
            f"Don't pip install into the environment: '{cmd}'. Use `uv add <pkg>` so uv.lock records it for review."
        )

    kind = secret_kind(cmd)
    if kind:
        block(
            f"That looks like {kind} inlined in the command. Reference it via an environment variable instead."
        )

    for match in DUMP_SECRET.finditer(cmd):
        if any(is_secret_file(arg) for arg in match.group(3).split()):
            block(
                f"This prints a secret file into the transcript: '{cmd}'. Ask the human for the specific value you need."
            )

    if GIT_COMMIT.search(cmd) and current_branch(cwd) in PROTECTED_BRANCHES:
        block(
            "You are on the default branch. Create a branch first (git switch -c <type>/<topic>); all changes reach main through a PR."
        )
    push = GIT_PUSH.search(cmd)
    if push:
        refspec = push.group(1)
        if re.search(r"(\s|:)(main|master)(\s|$)", refspec) or (
            current_branch(cwd) in PROTECTED_BRANCHES and not refspec.strip(" -")
        ):
            block(
                "Pushing to the default branch is not allowed. Push your feature branch and open a PR."
            )

    if re.search(r"\bgit\s+reset\s+--hard\b", cmd):
        warn(f"git reset --hard discards uncommitted work. Proceeding: '{cmd}'")
    if re.search(r"\bchmod\s+(-R\s+)?777\b", cmd):
        warn(f"chmod 777 makes files world-writable. Proceeding: '{cmd}'")


def main() -> None:
    payload = read_payload()
    cmd = str(tool_input(payload).get("command") or "")
    if cmd:
        check(cmd, payload.get("cwd"))
    allow()


if __name__ == "__main__":
    main()
