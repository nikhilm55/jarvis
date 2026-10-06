"""PreToolUse guard for Read: keep secrets and real user data out of the model's context.

Wire: event=PreToolUse, matcher="Read". One job: veto reading secret files or
Jarvis user data (recordings, transcripts, memory, grants) — see docs/ai/policy.md.
"""

from __future__ import annotations

import re

from _hooklib import allow, block, is_secret_file, normalise, read_payload, tool_input

USER_DATA = re.compile(
    r"(^|/)\.local/share/jarvis/|(^|/)AppData/Local/jarvis/|(^|/)\.config/jarvis/secrets",
    re.I,
)


def main() -> None:
    path = normalise(str(tool_input(read_payload()).get("file_path") or ""))
    if path and is_secret_file(path):
        block(
            f"{path} looks like secrets or key material. Ask the human for the specific value you need."
        )
    if path and USER_DATA.search(path):
        block(
            f"{path} is real Jarvis user data (Restricted class). Use synthetic fixtures under tests/fixtures/ instead."
        )
    allow()


if __name__ == "__main__":
    main()
