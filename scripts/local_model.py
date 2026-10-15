"""Offload implementation drafts to a local model, with no Claude in the loop.

The local model is any OpenAI-compatible chat server (we use Qwen under llama-server). It only
receives text and only returns text; this script writes its files and runs the checks.

  ask        one prompt in, one answer out (test-case lists, fixtures, docstrings, PR drafts)
  implement  the harness contract (harness/README.md): plan, tests first then locked,
             search/replace edits, ruff + mypy + pytest + scope check every round, stall
             stop, then a fresh-context self-review

Usage:
  export LOCAL_LLM_URL=http://<host>:8080/v1      # never commit the address
  uv run python scripts/local_model.py ask "List edge cases for parsing '30 percent'"
  uv run python scripts/local_model.py implement --spec brief.md \\
      --write src/jarvis/x.py tests/test_x.py --read src/jarvis/y.py \\
      --test tests/test_x.py --rounds 5 --log-dir .superpowers/runs/x

`implement` only writes the files named in --write (inside the repo) and never commits.
Exit 0 when ruff, mypy and the tests pass and the review finds nothing missing; 1 otherwise (the
files keep the last attempt for a finisher to complete); 2 on a usage or connection error. Every
prompt, reply and check output is saved in --log-dir, plus plan.json, review.json and
summary.json. See harness/README.md.
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
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_checks as hc

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_FILE = ROOT / "harness" / "qwen" / "system.md"
REVIEW_STATUSES = ("met", "missing", "unsure")
EDIT_LIMIT = 150  # lines; a bigger file is edited with SEARCH/REPLACE blocks, never rewritten

WHOLE_FORMAT = (
    "Output format: return the COMPLETE content of `{rel}` in ONE fenced ```python block and "
    "nothing else."
)
EDIT_FORMAT = (
    "Output format: `{rel}` already exists; return ONLY SEARCH/REPLACE blocks and no other text.\n"
    "<<<<<<< SEARCH\n(lines copied exactly from the current file; they must match exactly once)\n"
    "=======\n(the replacement lines)\n>>>>>>> REPLACE\n"
    "Keep each SEARCH short but unique, and do not rewrite code the task does not need."
)
PLAN_FORMAT = (
    "Output format: ONLY a JSON object, no prose: "
    '{"files": {"<path>": ["<public name(signature) -> return>", ...]}, '
    '"tests": [{"requirement": "<number or short text from the brief>", '
    '"test": "<test function name>"}]}. '
    "Every file you will write gets an entry; every requirement maps to a named test."
)

REVIEW_SYSTEM = (
    "You are a strict code reviewer. You did not write this code. Check the change against each "
    "numbered requirement of the brief and judge only what the diff shows."
)
REVIEW_FORMAT = (
    "Output format: ONLY a JSON list, one item per requirement: "
    '{"requirement": "<number or text>", "status": "met" | "missing" | "unsure", '
    '"note": "<one line>"}. Use "missing" only when the change plainly lacks it.'
)

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
    code, out = run([*uv, "ruff", "check", "--quiet", "--output-format=concise", *py], repo)
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


def json_values(text: str) -> Iterator[Any]:
    """Every JSON object or array that starts somewhere in a reply (fenced or bare)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            yield decoder.raw_decode(text, match.start())[0]
        except json.JSONDecodeError:
            continue


def valid_plan(value: Any) -> bool:
    shape = {"files": dict, "tests": list}
    return isinstance(value, dict) and all(isinstance(value.get(k), t) for k, t in shape.items())


class Implementer:
    """Holds one `implement` run: the repo, the manifest, the plan, the test lock, the log."""

    def __init__(self, opts: argparse.Namespace) -> None:
        self.opts = opts
        self.repo: Path = opts.repo.resolve()
        self.log: Path = opts.log_dir
        self.spec = opts.spec.read_text(encoding="utf-8")
        self.system = SYSTEM_FILE.read_text(encoding="utf-8")
        self.context = "\n\n".join(
            f"### {p} (read-only, existing)\n```python\n{self.current(p)}```" for p in opts.read
        )
        self.tests = [p for p in opts.write if p.startswith("tests/")]
        self.impl = [p for p in opts.write if p not in self.tests]
        self.order = self.tests + self.impl
        self.existing = {p for p in opts.write if (self.repo / p).exists()}
        self.plan: dict[str, Any] | None = None
        self.baseline: dict[str, hc.TestStats] = {}
        self.notes: dict[str, list[str]] = {}
        self.weakened: list[dict[str, Any]] = []
        self.dirty: set[str] = set()
        self.stray: list[str] = []

    def current(self, rel: str) -> str:
        path = self.repo / rel
        return path.read_text(encoding="utf-8") if path.exists() else "(file does not exist yet)"

    def call(self, fmt: str, prompt: str, tag: str, system: str | None = None) -> str:
        """One call: the system prompt is harness/qwen/system.md, the output format is ours."""
        msgs = [
            {"role": "system", "content": f"{system or self.system}\n\n{fmt}"},
            {"role": "user", "content": prompt},
        ]
        (self.log / f"{tag}.prompt.md").write_text(prompt, encoding="utf-8")
        reply = chat(msgs, self.opts.max_tokens, self.opts.timeout)
        (self.log / f"{tag}.reply.md").write_text(reply, encoding="utf-8")
        return reply

    def brief(self) -> str:
        plan = f"## Plan (follow it)\n```json\n{json.dumps(self.plan, indent=2)}\n```\n\n"
        return (
            f"## Task spec\n{self.spec}\n\n{plan if self.plan else ''}"
            f"## Existing code you must use as-is\n{self.context}"
        )

    def make_plan(self) -> None:
        """Plan first: public names per file, and every requirement mapped to a named test."""
        prompt = f"{self.brief()}\n\n## Files to write\n" + "\n".join(self.opts.write)
        for attempt in (1, 2):
            reply = self.call(PLAN_FORMAT, prompt, f"plan-{attempt}")
            self.plan = next((v for v in json_values(reply) if valid_plan(v)), None)
            if self.plan:
                (self.log / "plan.json").write_text(json.dumps(self.plan, indent=2), "utf-8")
                return
            prompt += "\n\nYour last reply was not the required JSON object. Return only it."
        print("plan: no valid JSON after a retry; continuing without one", file=sys.stderr)

    def write(self, rel: str, prompt: str, tag: str) -> None:
        """Existing or big files change by SEARCH/REPLACE; new small ones are written whole."""
        path = self.repo / rel
        old = path.read_text(encoding="utf-8") if path.exists() else None
        editing = old is not None and (rel in self.existing or len(old.splitlines()) > EDIT_LIMIT)
        reply = self.call((EDIT_FORMAT if editing else WHOLE_FORMAT).format(rel=rel), prompt, tag)
        self.notes[rel], code = [], None
        if editing and old is not None:
            edits = hc.parse_edits(reply)
            code, self.notes[rel] = hc.apply_edits(old, edits)
            if not edits:
                code, self.notes[rel] = None, ["no SEARCH/REPLACE block in the reply"]
        else:
            code = last_code_block(reply)
            if code is None:
                self.notes[rel] = ["no code block in the reply"]
        if code is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding="utf-8")

    def draft(self) -> None:
        """Round 0: the test files first (from the brief), then the implementation."""
        for i, rel in enumerate(self.order):
            done = "\n\n".join(
                f"### {q} (written so far)\n```python\n{self.current(q)}```" for q in self.order[:i]
            )
            kind = "tests (the implementation does not exist yet)" if rel in self.tests else "code"
            prompt = (
                f"{self.brief()}\n\n{done}\n\n## Current content of {rel}\n"
                f"```python\n{self.current(rel)}```\n\nWrite the {kind} for `{rel}`."
            )
            self.write(rel, prompt, f"r0-{i}-{Path(rel).name}")

    def fix(self, round_no: int, report: str) -> None:
        """Only implementation files change, plus a test file that itself fails to import."""
        (self.log / f"r{round_no}.checks.txt").write_text(report, encoding="utf-8")
        broken = hc.collection_errors(report)
        for i, rel in enumerate(self.impl + [t for t in self.tests if t in broken]):
            routed = hc.errors_for_file(report, rel)
            if not routed and not self.notes.get(rel):
                continue
            files = "\n\n".join(
                f"### {q}{' (locked tests)' if q in self.tests else ''}\n"
                f"```python\n{self.current(q)}```"
                for q in self.order
            )
            errors = "\n\n".join(f"{k}:\n{trim(v, 60)}" for k, v in routed.items())
            notes = "\n".join(f"- {n}" for n in self.notes.get(rel, []))
            prompt = (
                f"{self.brief()}\n\n## The files written for this task\n{files}\n\n"
                f"## The checks failed (the part that concerns `{rel}`)\n```\n{errors}\n```\n\n"
                f"## Notes from the harness\n{notes or '(none)'}\n\nFix `{rel}`."
            )
            self.write(rel, prompt, f"r{round_no}-{i}-{Path(rel).name}")

    def lock_tests(self, round_no: int, before: dict[str, str]) -> None:
        """Record the test counts after round 0; later, restore any test file that got weaker."""
        for rel in self.tests:
            stats = hc.test_stats(self.current(rel))
            if stats is None:
                continue
            problems = hc.weakening(self.baseline.setdefault(rel, stats), stats)
            if problems and rel in before:
                (self.repo / rel).write_text(before[rel], encoding="utf-8")
                self.weakened.append({"round": round_no, "file": rel, "problems": problems})
                why = "; ".join(problems)
                self.notes.setdefault(rel, []).append(f"reverted, tests may not shrink: {why}")

    def porcelain(self) -> str:
        code, out = run(["git", "status", "--porcelain", "--untracked-files=all"], self.repo)
        if code:
            raise LocalModelError(f"--repo must be a git repository:\n{trim(out, 5)}")
        return out

    def out_of_scope(self) -> bool:
        log = os.path.relpath(self.log.resolve(), self.repo).replace(os.sep, "/")
        self.stray = hc.scope_violations(
            self.porcelain(), set(self.opts.write), self.dirty, (f"{log}/",)
        )
        return bool(self.stray)

    def iterate(self) -> tuple[str, int, str]:
        """Round 0 then fix rounds. Returns (status, fix rounds, last failing report)."""
        cache = self.log / "mypy-cache"
        self.lock_tests(0, {})
        ok, report = check(self.repo, self.opts.write, self.opts.test, cache)
        seen: str | None = None
        rounds = 0
        while True:
            if self.out_of_scope():
                return "scope_violation", rounds, report
            if ok:
                return "green", rounds, ""
            if hc.fingerprint(report) == seen:
                return "stalled", rounds, report
            if rounds >= self.opts.rounds:
                break
            seen, rounds = hc.fingerprint(report), rounds + 1
            before = {t: self.current(t) for t in self.tests}
            self.fix(rounds, report)
            self.lock_tests(rounds, before)
            ok, report = check(self.repo, self.opts.write, self.opts.test, cache)
        return ("test_weakened" if self.weakened else "red"), rounds, report

    def diff(self) -> str:
        parts = []
        for rel in self.opts.write:
            if rel in self.existing:
                parts.append(run(["git", "diff", "--", rel], self.repo)[1])
            else:
                parts.append(f"### new file {rel}\n```python\n{self.current(rel)}```")
        return "\n\n".join(parts)

    def review(self) -> tuple[list[dict[str, Any]], bool]:
        """A fresh call with no generation history; it only reports, it never edits."""
        prompt = f"{self.brief()}\n\n## The change\n{self.diff()}\n\nReview it."
        reply = self.call(REVIEW_FORMAT, prompt, "review", REVIEW_SYSTEM)
        items = next((v for v in json_values(reply) if isinstance(v, list)), None)
        good = [
            i for i in items or [] if isinstance(i, dict) and i.get("status") in REVIEW_STATUSES
        ]
        (self.log / "review.json").write_text(json.dumps(good, indent=2), encoding="utf-8")
        return good, items is not None

    def run(self) -> int:
        start = time.time()
        self.dirty = hc.porcelain_paths(self.porcelain())
        self.make_plan()
        self.draft()
        status, rounds, report = self.iterate()
        review, reviewed = self.review() if status == "green" else ([], False)
        missing = [str(i.get("requirement")) for i in review if i["status"] == "missing"]
        summary = {
            "status": status,
            "plan": self.plan is not None,
            "tests_locked_counts": {k: asdict(v) for k, v in self.baseline.items()},
            "weakening_events": self.weakened,
            "rounds": rounds,
            "review_missing": missing,
            "reviewed": reviewed,
            "scope_violations": self.stray,
            "minutes": round((time.time() - start) / 60, 1),
            "files": self.opts.write,
            "remaining": report,
        }
        (self.log / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in summary.items() if k != "remaining"}))
        if report:
            print(trim(report, 40))
        return 0 if status == "green" and not missing else 1


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
