"""Offload implementation drafts to a local model, with no Claude in the loop.

The local model is any OpenAI-compatible chat server (we use Qwen under llama-server). It only
receives text and only returns text; this script writes its files and runs the checks.

  ask        one prompt in, one answer out (test-case lists, fixtures, docstrings, PR drafts)
  implement  write the manifest's files, run ruff + mypy + pytest, feed failures back, repeat

Usage:
  export LOCAL_LLM_URL=http://<host>:8080/v1      # never commit the address
  uv run python scripts/local_model.py ask "List edge cases for parsing '30 percent'"
  uv run python scripts/local_model.py implement --spec brief.md \\
      --write src/jarvis/x.py tests/test_x.py --read src/jarvis/y.py \\
      --test tests/test_x.py --rounds 5 --log-dir .superpowers/runs/x

`implement` only writes the files named in --write (inside the repo) and never commits.
Exit 0 when ruff, mypy and the tests pass; 1 when the rounds run out (the files keep the last
attempt for a finisher to complete); 2 on a usage or connection error. Every prompt, reply and
check output is saved in --log-dir, plus summary.json. See docs/ai/dev-pipeline.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

HOUSE_RULES = """You are a careful senior Python engineer implementing one task in an existing repo.
House rules (all are checked automatically):
- Python 3.11+, full type hints, mypy --strict clean, ruff clean (line length 100, max 5 args).
- Every import you use must be present; no unused imports.
- Every text file I/O and subprocess.run(text=True) passes encoding="utf-8"; never shell=True.
- Tests use pytest's `monkeypatch`/`tmp_path` fixtures (never construct pytest.MonkeyPatch()
  yourself), assert real behaviour, and never touch the network, real user dirs, audio devices
  or the display.
- No try/except/pass; don't swallow errors silently.
Repo facts: src layout - the package is `jarvis` (import `from jarvis.x import y`, NEVER
`from src.jarvis...`); tests live in `tests/` and import the package the same way;
tests/conftest.py already points JARVIS_HOME at a tmp dir.
If mypy says a file is "found twice under different module names", an import uses `src.`.
Output format: return the COMPLETE content of the requested file in ONE fenced ```python block
and nothing else."""

CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


class LocalModelError(RuntimeError):
    """The local model server could not be reached or answered with garbage."""


def endpoint() -> str:
    url = os.environ.get("LOCAL_LLM_URL", "").rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise LocalModelError("set LOCAL_LLM_URL to the server's http(s)://…/v1 base URL")
    return url + "/chat/completions"


def chat(messages: list[dict[str, str]], max_tokens: int, timeout: int) -> str:
    """One chat completion. Thinking is off: with it on, the budget goes into reasoning."""
    body = {
        "model": os.environ.get("LOCAL_LLM_MODEL", "qwen"),
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": messages,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(  # noqa: S310 - endpoint() allows http(s) only
        endpoint(), json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked
            out: dict[str, Any] = json.load(resp)
    except OSError as exc:
        raise LocalModelError(f"local model unavailable: {exc}") from exc
    return str(out["choices"][0]["message"].get("content") or "")


def last_code_block(text: str) -> str | None:
    blocks = CODE_BLOCK.findall(text)
    return blocks[-1].rstrip() + "\n" if blocks else None


def trim(text: str, lines: int = 120) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def inside_repo(repo: Path, rel: str) -> bool:
    target = (repo / rel).resolve()
    return repo in target.parents


def run(cmd: list[str], repo: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=900, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


def check(repo: Path, files: list[str], tests: list[str], cache: Path) -> tuple[bool, str]:
    """ruff (after autofix), mypy with the project config, then the tests. Returns (ok, report)."""
    py = [f for f in files if f.endswith(".py")]
    uv = ["uv", "run", "--quiet"]
    run([*uv, "ruff", "format", *py], repo)
    run([*uv, "ruff", "check", "--fix", "--quiet", *py], repo)
    report = []
    code, out = run([*uv, "ruff", "check", "--quiet", *py], repo)
    if code:
        report.append("RUFF:\n" + trim(out, 60))
    # a per-run cache so stale entries never leak in
    code, out = run([*uv, "mypy", "--cache-dir", str(cache)], repo)
    if code:
        report.append("MYPY:\n" + trim(out, 60))
    code, out = run([*uv, "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], repo)
    if code:
        report.append("PYTEST:\n" + trim(out, 120))
    return not report, "\n\n".join(report)


class Implementer:
    """Holds one `implement` run: the repo, the manifest and the log directory."""

    def __init__(self, opts: argparse.Namespace) -> None:
        self.opts = opts
        self.repo: Path = opts.repo.resolve()
        self.log: Path = opts.log_dir
        self.spec = opts.spec.read_text(encoding="utf-8")
        self.context = "\n\n".join(
            f"### {p} (read-only, existing)\n```python\n{self.current(p)}```" for p in opts.read
        )

    def current(self, rel: str) -> str:
        path = self.repo / rel
        return path.read_text(encoding="utf-8") if path.exists() else "(file does not exist yet)"

    def write(self, rel: str, prompt: str, tag: str) -> None:
        msgs = [{"role": "system", "content": HOUSE_RULES}, {"role": "user", "content": prompt}]
        (self.log / f"{tag}.prompt.md").write_text(prompt, encoding="utf-8")
        reply = chat(msgs, self.opts.max_tokens, self.opts.timeout)
        (self.log / f"{tag}.reply.md").write_text(reply, encoding="utf-8")
        code = last_code_block(reply)
        if code is None:
            print(f"{tag}: no code block in the reply", file=sys.stderr)
            return
        dest = self.repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")

    def draft(self) -> None:
        """Round 0: draft each file in order; later files see the earlier drafts."""
        for i, rel in enumerate(self.opts.write):
            others = "\n\n".join(
                f"### {q} (written so far)\n```python\n{self.current(q)}```"
                for q in self.opts.write[:i]
            )
            prompt = (
                f"## Task spec\n{self.spec}\n\n## Existing code you must use as-is\n"
                f"{self.context}\n\n{others}\n\n"
                f"## Current content of {rel}\n```python\n{self.current(rel)}```\n\n"
                f"Write the complete file `{rel}` for this task."
            )
            self.write(rel, prompt, f"r0-{i}-{Path(rel).name}")

    def fix(self, round_no: int, report: str) -> None:
        (self.log / f"r{round_no}.checks.txt").write_text(report, encoding="utf-8")
        for i, rel in enumerate(self.opts.write):
            files = "\n\n".join(
                f"### {q}\n```python\n{self.current(q)}```" for q in self.opts.write
            )
            prompt = (
                f"## Task spec\n{self.spec}\n\n## Existing code (read-only)\n{self.context}\n\n"
                f"## The files written for this task\n{files}\n\n"
                f"## The checks failed\n```\n{report}\n```\n\n"
                f"Fix the problems that belong to `{rel}` (if none do, return it unchanged). "
                f"Return the complete corrected `{rel}`."
            )
            self.write(rel, prompt, f"r{round_no}-{i}-{Path(rel).name}")

    def run(self) -> int:
        start = time.time()
        cache = self.log / "mypy-cache"
        self.draft()
        ok, report = check(self.repo, self.opts.write, self.opts.test, cache)
        rounds = 0
        while not ok and rounds < self.opts.rounds:
            rounds += 1
            self.fix(rounds, report)
            ok, report = check(self.repo, self.opts.write, self.opts.test, cache)
        summary = {
            "status": "green" if ok else "red",
            "fix_rounds": rounds,
            "minutes": round((time.time() - start) / 60, 1),
            "files": self.opts.write,
            "remaining": "" if ok else report,
        }
        (self.log / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in summary.items() if k != "remaining"}))
        if not ok:
            print(trim(report, 40))
        return 0 if ok else 1


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="one prompt in, one answer out")
    ask.add_argument("prompt", nargs="?", help="the prompt (default: read stdin)")
    ask.add_argument("--system", type=Path, help="a file with the system prompt")
    ask.add_argument("--max-tokens", type=int, default=4000)
    ask.add_argument("--timeout", type=int, default=600)

    imp = sub.add_parser("implement", help="write files and fix them against the checks")
    imp.add_argument("--repo", type=Path, default=ROOT)
    imp.add_argument("--spec", required=True, type=Path, help="the task brief (markdown)")
    imp.add_argument("--write", nargs="+", required=True, help="files the model writes")
    imp.add_argument("--read", nargs="*", default=[], help="files it reads as context")
    imp.add_argument("--test", nargs="+", required=True, help="pytest targets")
    imp.add_argument("--rounds", type=int, default=5)
    imp.add_argument("--max-tokens", type=int, default=8000)
    imp.add_argument("--timeout", type=int, default=900)
    imp.add_argument("--log-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    opts = parse(argv)
    try:
        if opts.command == "ask":
            msgs = []
            if opts.system:
                msgs.append({"role": "system", "content": opts.system.read_text(encoding="utf-8")})
            prompt = opts.prompt if opts.prompt is not None else sys.stdin.read()
            msgs.append({"role": "user", "content": prompt})
            print(chat(msgs, opts.max_tokens, opts.timeout).strip())
            return 0
        repo = opts.repo.resolve()
        outside = [f for f in opts.write if not inside_repo(repo, f)]
        if outside:
            print(f"refusing to write outside the repo: {outside}", file=sys.stderr)
            return 2
        opts.log_dir.mkdir(parents=True, exist_ok=True)
        return Implementer(opts).run()
    except LocalModelError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
