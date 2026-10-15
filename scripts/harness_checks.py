"""Pure sensors for the local-model loop: test-weakening guard, SEARCH/REPLACE
edit parsing and applying, failure fingerprint, per-file error routing,
collection-error detection and the git scope check.

Stdlib only: ast, re, dataclasses. No network, no subprocess, no file I/O.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import ClassVar

MARKS = ("skip", "skipif", "xfail")


@dataclass(frozen=True)
class TestStats:
    """Counts of test-related constructs in a Python source file."""

    __test__: ClassVar[bool] = False  # not a pytest test class

    tests: int
    asserts: int
    raises: int
    skips: int


def _is_pytest_raises(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "raises"
    )


def _is_skip(node: ast.AST) -> bool:
    """`pytest.mark.skip|skipif|xfail` (called or not) and `pytest.skip|xfail`."""
    if not isinstance(node, ast.Attribute):
        return False
    base = node.value
    if isinstance(base, ast.Attribute) and base.attr == "mark":
        base = base.value
        return isinstance(base, ast.Name) and base.id == "pytest" and node.attr in MARKS
    return isinstance(base, ast.Name) and base.id == "pytest" and node.attr in ("skip", "xfail")


def test_stats(source: str) -> TestStats | None:
    """Return TestStats for *source*, or None when the source does not parse."""
    try:
        nodes = list(ast.walk(ast.parse(source)))
    except SyntaxError:
        return None
    funcs = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return TestStats(
        tests=sum(f.name.startswith("test") for f in funcs),
        asserts=sum(isinstance(n, ast.Assert) for n in nodes),
        raises=sum(
            _is_pytest_raises(i.context_expr)
            for n in nodes
            if isinstance(n, (ast.With, ast.AsyncWith))
            for i in n.items
        ),
        skips=sum(_is_skip(n) for n in nodes),
    )


def weakening(before: TestStats, after: TestStats) -> list[str]:
    """Return one message per weakening problem; [] when fine."""
    msgs: list[str] = []
    if after.tests < before.tests:
        msgs.append(f"tests decreased from {before.tests} to {after.tests}")
    if after.asserts < before.asserts:
        msgs.append(f"asserts decreased from {before.asserts} to {after.asserts}")
    if after.raises < before.raises:
        msgs.append(f"raises decreased from {before.raises} to {after.raises}")
    if after.skips > before.skips:
        msgs.append(f"skips increased from {before.skips} to {after.skips}")
    return msgs


@dataclass(frozen=True)
class Edit:
    """A single SEARCH/REPLACE edit block."""

    search: str
    replace: str


EDIT_BLOCK = re.compile(r"^<<<<<<< SEARCH\n(.*?)^=======\n(.*?)^>>>>>>> REPLACE$", re.M | re.S)


def parse_edits(reply: str) -> list[Edit]:
    """Aider-style SEARCH/REPLACE blocks; text between them and unterminated blocks are ignored."""
    return [Edit(m.group(1), m.group(2)) for m in EDIT_BLOCK.finditer(reply)]


def apply_edits(content: str, edits: list[Edit]) -> tuple[str, list[str]]:
    """Apply *edits* in order to *content*; return (new_content, errors)."""
    errors: list[str] = []
    for idx, edit in enumerate(edits, start=1):
        if not edit.search:
            errors.append(f"edit {idx}: SEARCH is empty")
            continue
        count = content.count(edit.search)
        if count == 0:
            errors.append(f"edit {idx}: SEARCH not found")
            continue
        if count > 1:
            errors.append(f"edit {idx}: SEARCH matches {count} times")
            continue
        content = content.replace(edit.search, edit.replace, 1)
    return content, errors


PYTEST_ID = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$")
MYPY_LINE = re.compile(r"^(\S+):(\d+): error: .*\[([\w-]+)\]$")
RUFF_LINE = re.compile(r"^(\S+):(\d+):\d+: (\w+) ")
SECTION = re.compile(r"^(RUFF|MYPY|PYTEST):$")


def fingerprint(report: str) -> str:
    """Normalised identity of a failing report: test ids plus mypy/ruff codes with file:line."""
    found: set[str] = set()
    for line in report.splitlines():
        if m := PYTEST_ID.match(line):
            found.add(m.group(1))
        elif m := MYPY_LINE.match(line):
            found.add(f"mypy {m.group(1)}:{m.group(2)} {m.group(3)}")
        elif m := RUFF_LINE.match(line):
            found.add(f"ruff {m.group(1)}:{m.group(2)} {m.group(3)}")
    if found:
        return "\n".join(sorted(found))
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", report)).strip()


def split_report(report: str) -> dict[str, str]:
    """Split a report into its RUFF / MYPY / PYTEST sections (a section runs to the next one)."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in report.splitlines():
        if m := SECTION.match(line):
            current = sections.setdefault(m.group(1), [])
        elif current is not None:
            current.append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def errors_for_file(report: str, rel: str) -> dict[str, str]:
    """The lines of each section that concern `rel`; pytest's FAILED/ERROR summaries always stay."""
    routed: dict[str, str] = {}
    for key, body in split_report(report).items():
        summary = key == "PYTEST"
        kept = [
            line
            for line in body.splitlines()
            if rel in line or (summary and line.startswith(("FAILED ", "ERROR ")))
        ]
        if kept:
            routed[key] = "\n".join(kept)
    return routed


def collection_errors(report: str) -> set[str]:
    """Test files whose own collection or import failed (a file-level pytest ERROR)."""
    found = {m.group(1) for m in re.finditer(r"ERROR collecting (\S+)", report)}
    found |= {m.group(1) for m in re.finditer(r"^ERROR (\S+\.py)(?: - .*)?$", report, re.M)}
    return found


def porcelain_paths(porcelain: str) -> set[str]:
    """Paths from `git status --porcelain`: renames give both sides, quotes are stripped."""
    paths: set[str] = set()
    for line in porcelain.splitlines():
        if line.strip():
            paths |= {p.strip().strip('"') for p in line[3:].split(" -> ")}
    return paths


def scope_violations(
    porcelain: str, allowed: set[str], ignore: set[str], prefixes: tuple[str, ...] = ()
) -> list[str]:
    """Changed paths outside `allowed`, `ignore` (dirty before the run) and `prefixes`."""
    return sorted(
        p
        for p in porcelain_paths(porcelain)
        if p not in allowed and p not in ignore and not p.startswith(prefixes)
    )
