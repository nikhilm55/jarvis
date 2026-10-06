"""M0b harness: cold (process per turn) vs warm (one stream-json session) Claude Code latency.

Usage: uv run python spikes/M0b-brain-latency/measure.py --model sonnet --turns 20
Writes docs/spikes/M0b-brain-latency.data.csv. Runs Claude Code isolated from user settings
(--setting-sources project in an empty temp dir, --strict-mcp-config) with only the policy hook.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "docs" / "spikes" / "M0b-brain-latency.data.csv"

ANSWER = [
    "Reply with exactly: Teams is open.",
    "In one short sentence, what is 17 times 3?",
    "Reply with exactly one word: ready",
    "Say 'Sent to Rahul Sharma.' and nothing else.",
    "In under ten words, tell me the capital of France.",
]
TOOL = [
    "Use the Bash tool to run `echo jarvis-ok`, then reply with exactly: done",
    "Run `echo volume-30` with Bash, then reply with one word: set",
    "With Bash run `echo opened-teams` and then answer only: open",
]
DENY = "Use the Bash tool to run `echo DENYME`, then tell me in one sentence what happened."


def base_cmd(model: str, settings: Path, warm: bool) -> list[str]:
    claude = shutil.which("claude") or "claude"
    cmd = [
        claude,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--model",
        model,
        "--setting-sources",
        "project",
        "--settings",
        str(settings),
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps({"mcpServers": {}}),
        "--tools",
        "Bash",
        "--allowedTools",
        "Bash(echo *)",
        "--no-session-persistence",
    ]
    if warm:
        cmd += ["--input-format", "stream-json"]
    return cmd


def read_turn(stream: IO[str], start: float) -> dict[str, Any]:
    """Consume events until the turn's result; return timings and outcome."""
    first_token = None
    while True:
        line = stream.readline()
        if not line:
            return {"ttft_s": first_token, "total_s": None, "ok": False, "text": "EOF"}
        event = json.loads(line)
        kind = event.get("type")
        if first_token is None and kind == "stream_event":
            delta = event.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta":
                first_token = time.perf_counter() - start
        if kind == "result":
            return {
                "ttft_s": first_token,
                "total_s": time.perf_counter() - start,
                "ok": not event.get("is_error", False),
                "text": str(event.get("result", ""))[:80].replace("\n", " "),
                "api_ms": event.get("duration_api_ms"),
            }


def prompts(turns: int) -> list[tuple[str, str]]:
    seq = [("answer", p) for p in ANSWER] + [("tool", p) for p in TOOL]
    return [seq[i % len(seq)] for i in range(turns)]


def run_cold(model: str, settings: Path, cwd: Path, turns: int) -> list[dict[str, Any]]:
    rows = []
    for i, (kind, prompt) in enumerate(prompts(turns)):
        start = time.perf_counter()
        proc = subprocess.Popen(
            base_cmd(model, settings, warm=False),
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write(prompt)
        proc.stdin.close()
        rows.append({"mode": "cold", "turn": i, "kind": kind, **read_turn(proc.stdout, start)})
        proc.wait(timeout=60)
        print(rows[-1], file=sys.stderr)
    return rows


def run_warm(model: str, settings: Path, cwd: Path, turns: int) -> list[dict[str, Any]]:
    rows = []
    proc = subprocess.Popen(
        base_cmd(model, settings, warm=True),
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin and proc.stdout
    plan = [("warmup", "Reply with exactly: ok"), *prompts(turns), ("deny", DENY)]
    for i, (kind, prompt) in enumerate(plan):
        message = {"type": "user", "message": {"role": "user", "content": prompt}}
        start = time.perf_counter()
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        rows.append({"mode": "warm", "turn": i - 1, "kind": kind, **read_turn(proc.stdout, start)})
        print(rows[-1], file=sys.stderr)
    proc.stdin.close()
    proc.wait(timeout=60)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--modes", default="cold,warm")
    args = parser.parse_args()

    (HERE / "hook_times.csv").unlink(missing_ok=True)
    stub = subprocess.Popen([sys.executable, str(HERE / "policy_stub.py")])
    time.sleep(0.5)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            hook = f"{sys.executable} {HERE / 'policy_hook.py'}"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [{"type": "command", "command": hook, "timeout": 5}],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            rows: list[dict[str, Any]] = []
            if "cold" in args.modes:
                rows += run_cold(args.model, settings, Path(tmp), args.turns)
            if "warm" in args.modes:
                rows += run_warm(args.model, settings, Path(tmp), args.turns)
    finally:
        stub.terminate()

    new_file = not OUT.exists()
    with OUT.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "model",
                "mode",
                "turn",
                "kind",
                "ttft_s",
                "total_s",
                "api_ms",
                "ok",
                "text",
            ],
        )
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow(
                {"model": args.model, **{k: row.get(k) for k in writer.fieldnames if k != "model"}}
            )
    print(f"wrote {len(rows)} rows to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
