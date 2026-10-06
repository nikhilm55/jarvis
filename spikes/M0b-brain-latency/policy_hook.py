"""PreToolUse hook: ask the policy stub, then allow or deny. Appends its own runtime to hook_times.csv."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

START = time.perf_counter()
payload = sys.stdin.read()
request = urllib.request.Request(
    "http://127.0.0.1:8765/decide",
    data=payload.encode("utf-8"),
    method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 — fixed loopback URL
    decision = json.loads(response.read())["decision"]
elapsed_ms = (time.perf_counter() - START) * 1000
with (Path(__file__).parent / "hook_times.csv").open("a", encoding="utf-8") as log:
    log.write(f"{decision},{elapsed_ms:.1f}\n")
out = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": "Blocked by Jarvis policy gate (spike stub)."
        if decision == "deny"
        else "ok",
    }
}
print(json.dumps(out))
