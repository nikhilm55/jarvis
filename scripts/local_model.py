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
import hashlib
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


def check(
    repo: Path, files: list[str], tests: list[str], cache: Path, minimum: int = 0
) -> tuple[bool, str]:
    """ruff (after autofix), mypy with the project config, then the tests. Returns (ok, report).
    pytest is green only when its exit code is 0 AND its last line says `N passed` (N at least
    `minimum`, the locked tests' count) with nothing failed: an implementation can fake the exit
    code (atexit, os._exit) but not print a believable summary."""
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
    # the repo's addopts already hold a -q; a second one would drop the summary line
    pytest = [*uv, "pytest", "-o", "addopts=--strict-markers", "-q", "-x", "-p", "no:cacheprovider"]
    code, out = run([*pytest, *tests], repo)
    if code or not hc.pytest_clean(out, minimum):
        last = (out.strip().splitlines() or [""])[-1]
        note = "" if code else f"{hc.CLEAN_MSG} (exit 0, last line: {last!r})\n"
        report.append("PYTEST:\n" + note + trim(out, 120))
    return not report, "\n\n".join(report)


def json_values(text: str) -> Iterator[Any]:
    """Every JSON object or array that starts somewhere in a reply (fenced or bare)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            yield decoder.raw_decode(text, match.start())[0]
        except json.JSONDecodeError:
            continue


def canonical(repo: Path, rel: str) -> str:
    """`./a/../b.py`, an absolute path inside the repo and `b.py` all become `b.py`."""
    return Path(os.path.relpath((repo / rel).resolve(), repo)).as_posix()


def is_test(rel: str) -> bool:
    path = Path(rel)
    return "tests" in path.parts[:-1] or path.name.startswith("test_") or path.name == "conftest.py"


def valid_plan(value: Any, write: list[str], required: list[str]) -> bool:
    """A plan names every file to write and covers every numbered requirement of the brief
    (or, when the brief has none, at least one) with `{"requirement": str, "test": str}` entries."""
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        return False
    tests = value.get("tests")
    if not isinstance(tests, list) or not tests:
        return False
    if not all(
        isinstance(t, dict)
        and isinstance(t.get("requirement"), str)
        and isinstance(t.get("test"), str)
        for t in tests
    ):
        return False
    named = {Path(os.path.normpath(k)).as_posix() for k in value["files"]}
    covered = {n for t in tests if (n := hc.req_number(t["requirement"])) is not None}
    pairs = [(t["requirement"], t["test"]) for t in tests]
    return set(write) <= named and set(required) <= covered and hc.plan_distinct(pairs, required)


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
        self.tests = [p for p in opts.write if is_test(p)]
        self.impl = [p for p in opts.write if p not in self.tests]
        self.order = self.tests + self.impl
        self.existing = {p for p in opts.write if (self.repo / p).exists()}
        self.plan: dict[str, Any] | None = None
        self.locked: dict[str, str] = {}  # test file -> the last content that passed the lock
        for rel in self.tests:
            before = self.read(rel)
            if before is not None and hc.test_stats(before) is not None:
                self.locked[rel] = before
        # the repo's mypy_path has src and scripts, so tests import `jarvis.x` and `tool`
        self.modules = [
            re.sub(r"^(?:src|scripts)/", "", p).removesuffix(".py").replace("/", ".")
            for p in self.impl
        ]
        self.culprits: dict[str, set[str]] = {}  # test file -> names its collection error quotes
        self.path_fixed: set[str] = set()  # test files that already had their one import-path fix
        self.good = {p: c for p in self.impl if (c := self.read(p)) is not None}
        self.tampered: list[dict[str, Any]] = []
        self.required = hc.brief_requirements(self.spec)
        self.lint_done: set[str] = set()
        self.disputes: list[dict[str, str]] = []
        self.notes: dict[str, list[str]] = {}
        self.weakened: list[dict[str, Any]] = []
        self.dirty: dict[str, str] = {}  # dirty before the run -> content hash
        self.top, self.prefix = self.repo, ""
        self.stray: list[str] = []

    def read(self, rel: str) -> str | None:
        path = self.repo / rel
        return path.read_text(encoding="utf-8") if path.exists() else None

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
            self.plan = next(
                (v for v in json_values(reply) if valid_plan(v, self.opts.write, self.required)),
                None,
            )
            if self.plan:
                (self.log / "plan.json").write_text(json.dumps(self.plan, indent=2), "utf-8")
                return
            prompt += (
                "\n\nYour last reply was not the required JSON object. Return only it, with an "
                f"entry under files for every one of: {', '.join(self.opts.write)} (an existing "
                "locked test file too), and tests entries of {requirement: string, test: string} "
                f"covering every numbered requirement ({', '.join(self.required) or 'any'})."
            )
        print("plan: no valid JSON after a retry; continuing without one", file=sys.stderr)

    def write(self, rel: str, prompt: str, tag: str) -> None:
        """Existing or big files change by SEARCH/REPLACE; new small ones are written whole."""
        path = self.repo / rel
        old = path.read_text(encoding="utf-8") if path.exists() else None
        editing = old is not None and (rel in self.existing or len(old.splitlines()) > EDIT_LIMIT)
        reply = self.call((EDIT_FORMAT if editing else WHOLE_FORMAT).format(rel=rel), prompt, tag)
        self.notes[rel], code = [], None
        for line in re.findall(r"^\s*TEST-DISPUTE:(.*)$", reply, re.M):
            self.disputes.append({"file": rel, "step": tag, "text": line.strip()})
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
            kind = "code"
            if rel in self.tests:
                kind = "tests (the implementation does not exist yet)"
                if rel in self.existing:
                    kind = "tests (its existing tests are locked: add new ones only, or no blocks)"
            prompt = (
                f"{self.brief()}\n\n{done}\n\n## Current content of {rel}\n"
                f"```python\n{self.current(rel)}```\n\nWrite the {kind} for `{rel}`."
            )
            self.write(rel, prompt, f"r0-{i}-{Path(rel).name}")

    def fix(self, round_no: int, report: str, lint: set[str]) -> None:
        """Implementation files change. A test file changes only to fix its own import (imports
        only) or, once, its own lint/mypy errors (annotations and imports only)."""
        (self.log / f"r{round_no}.checks.txt").write_text(report, encoding="utf-8")
        unlock = hc.collection_errors(report, self.modules) | lint
        self.culprits = {t: hc.collection_culprits(report, t) for t in unlock}
        for i, rel in enumerate(self.impl + [t for t in self.tests if t in unlock]):
            routed = hc.errors_for_file(report, rel)
            if not routed and not self.notes.get(rel):
                continue
            files = "\n\n".join(
                f"### {q}{' (locked tests)' if q in self.tests else ''}\n"
                f"```python\n{self.current(q)}```"
                for q in self.order
            )
            errors = "\n\n".join(f"{k}:\n{trim(v, 60)}" for k, v in routed.items())
            notes = [f"- {n}" for n in self.notes.get(rel, [])]
            if rel in self.tests:
                allowed = "type annotations and imports" if rel in lint else "import lines"
                notes.append(f"- only the {allowed} of this locked test file may change")
            prompt = (
                f"{self.brief()}\n\n## The files written for this task\n{files}\n\n"
                f"## The checks failed (the part that concerns `{rel}`)\n```\n{errors}\n```\n\n"
                f"## Notes from the harness\n{chr(10).join(notes) or '(none)'}\n\nFix `{rel}`."
            )
            self.write(rel, prompt, f"r{round_no}-{i}-{Path(rel).name}")

    def lock_tests(self, round_no: int, lint: frozenset[str] = frozenset()) -> None:
        """Hold every test file to the last content that passed the lock; put back what broke it.
        A file with no lock yet is locked at its first parseable state."""
        for rel in self.tests:
            new, old = self.read(rel), self.locked.get(rel)
            now = hc.test_stats(new) if new is not None else None
            if old is None:
                if new is not None and now is not None:
                    self.locked[rel] = new
                continue
            if new is None or now is None:
                problems = ["the test file is missing or does not parse"]
            else:
                extend, ann = round_no == 0 and rel in self.existing, rel in lint
                mods = [] if rel in self.path_fixed else self.modules
                rename = (mods, self.culprits.get(rel, set()))
                problems = hc.lock_violations(
                    old, new, extend=extend, annotations=ann, rename=rename
                )
                if not problems:
                    if mods and hc.lock_violations(old, new, extend=extend, annotations=ann):
                        self.path_fixed.add(rel)  # an import path was corrected: once per file
                    self.locked[rel] = new
                    continue
                problems += hc.weakening(hc.test_stats(old) or now, now)
            (self.repo / rel).write_text(old, encoding="utf-8")
            self.weakened.append({"round": round_no, "file": rel, "problems": problems})
            why = "; ".join(problems)
            self.notes.setdefault(rel, []).append(f"reverted, the tests are locked: {why}")
        self.guard_impl(round_no)

    def minimum(self) -> int:
        """At least this many tests must pass: the locked test files' collectable tests."""
        return sum(hc.collectable_tests(c) for c in self.locked.values())

    def guard_impl(self, round_no: int) -> None:
        """An implementation file may not reach into the test machinery; put back what does."""
        for rel in self.impl:
            new = self.read(rel)
            if new is None:
                continue
            known = hc.tamper_violations(self.good.get(rel, ""))
            problems = [p for p in hc.tamper_violations(new) if p not in known]
            if not problems:
                self.good[rel] = new
                continue
            if any(e["file"] == rel and e["problems"] == problems for e in self.tampered):
                continue  # already reported; a new file with no good content is kept as it is
            if rel in self.good:
                (self.repo / rel).write_text(self.good[rel], encoding="utf-8")
            self.tampered.append({"round": round_no, "file": rel, "problems": problems})
            fate = "reverted" if rel in self.good else "kept for the finisher"
            self.notes.setdefault(rel, []).append(f"{fate}: " + "; ".join(problems))

    def locate(self) -> None:
        """The git root and this repo's path inside it (porcelain paths are root-relative)."""
        code, out = run(["git", "rev-parse", "--show-toplevel", "--show-prefix"], self.repo)
        if code:
            raise LocalModelError(f"--repo must be a git repository:\n{trim(out, 5)}")
        top, _, prefix = out.partition("\n")
        self.top, self.prefix = Path(top), prefix.strip()

    def plan_tests(self) -> list[dict[str, Any]]:
        tests = (self.plan or {}).get("tests", [])
        return [t for t in tests if isinstance(t, dict)]

    def porcelain(self) -> str:
        return run(["git", "status", "--porcelain", "--untracked-files=all"], self.repo)[1]

    def digest(self, path: str) -> str:
        file = self.top / path
        return hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else ""

    def out_of_scope(self) -> bool:
        """Only the manifest may change. A file that was already dirty may not change further."""
        log = os.path.relpath(self.log.resolve(), self.top).replace(os.sep, "/")
        allowed = {self.prefix + w for w in self.opts.write}
        stray = hc.scope_violations(self.porcelain(), allowed, set(self.dirty), (f"{log}/",))
        stray += sorted(
            p for p, h in self.dirty.items() if p not in allowed and self.digest(p) != h
        )
        self.stray = stray
        return bool(stray)

    def iterate(self) -> tuple[str, int, str]:
        """Round 0 then fix rounds. Returns (status, fix rounds, last failing report)."""
        cache = self.log / "mypy-cache"
        self.lock_tests(0)
        ok, report = check(self.repo, self.opts.write, self.opts.test, cache, self.minimum())
        self.lock_tests(0)  # the formatter and ruff --fix are trusted: they join the lock
        seen: str | None = None
        rounds = 0
        while True:
            if self.out_of_scope():
                return "scope_violation", rounds, report
            if ok:
                return "green", rounds, ""
            lint = hc.only_test_errors(report, self.tests)
            if lint and lint <= self.lint_done:
                return "test_error", rounds, report
            if hc.fingerprint(report) == seen:
                return "stalled", rounds, report
            if rounds >= self.opts.rounds:
                break
            seen, rounds = hc.fingerprint(report), rounds + 1
            self.fix(rounds, report, lint)
            self.lint_done |= lint
            self.lock_tests(rounds, frozenset(lint))
            ok, report = check(self.repo, self.opts.write, self.opts.test, cache, self.minimum())
            self.lock_tests(rounds)
        return "red", rounds, report

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
        self.locate()
        self.dirty = {p: self.digest(p) for p in hc.porcelain_paths(self.porcelain())}
        self.make_plan()
        self.draft()
        planned = {str(t.get("test")).rsplit("::", 1)[-1] for t in self.plan_tests()}
        written = set().union(*(hc.test_names(self.read(t) or "") for t in self.tests))
        status, rounds, report = self.iterate()
        if status == "stalled" and self.disputes:
            status = "test_disputed"
        if self.tampered and status != "scope_violation":
            status = "sensor_tamper"
        elif self.weakened and status != "scope_violation":
            status = "test_weakened"
        review, reviewed = self.review() if status == "green" else ([], False)
        missing = [str(i.get("requirement")) for i in review if i["status"] == "missing"]
        plan_reqs = len({str(t.get("requirement")) for t in self.plan_tests()})
        reviewed_reqs = [str(i.get("requirement")) for i in review]
        complete = reviewed and hc.review_covers(reviewed_reqs, self.required, plan_reqs)
        summary = {
            "status": status,
            "plan": self.plan is not None,
            "tests_locked_counts": {
                k: asdict(st) for k, v in self.locked.items() if (st := hc.test_stats(v))
            },
            "weakening_events": self.weakened,
            "tamper_events": self.tampered,
            "test_disputes": self.disputes,
            "rounds": rounds,
            "review_missing": missing,
            "reviewed": reviewed,
            "review_complete": complete,
            "plan_tests_missing": sorted(planned - written),
            "scope_violations": self.stray,
            "minutes": round((time.time() - start) / 60, 1),
            "files": self.opts.write,
            "remaining": report,
        }
        (self.log / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in summary.items() if k != "remaining"}))
        if report:
            print(trim(report, 40))
        clean = not missing and complete and not (planned - written)
        return 0 if status == "green" and clean else 1


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
        opts.write = list(dict.fromkeys(canonical(repo, f) for f in opts.write))
        opts.log_dir.mkdir(parents=True, exist_ok=True)
        return Implementer(opts).run()
    except LocalModelError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
