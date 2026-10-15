"""Pure sensors for the local-model loop: test-weakening guard, SEARCH/REPLACE
edit parsing and applying, failure fingerprint, per-file error routing,
collection-error detection and the git scope check.

Stdlib only: ast, re, dataclasses. No network, no subprocess, no file I/O.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
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


def _statements(tree: ast.Module) -> list[ast.stmt]:
    return [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]


def _defined(tree: ast.Module) -> set[str]:
    """Names the file's non-import top-level statements define."""
    names: set[str] = set()
    for node in _statements(tree):
        names |= {n.name for n in [node] if hasattr(n, "name")}
        names |= {
            t.id
            for n in ast.walk(node)
            for t in getattr(n, "targets", [])
            if isinstance(t, ast.Name)
        }
    return names


def _bindings(tree: ast.Module) -> dict[str, frozenset[object]]:
    """What each top-level import binds, with a leading `src.` ignored."""
    found: dict[str, set[object]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                found.setdefault((a.asname or a.name).split(".")[0], set()).add(
                    a.name.removeprefix("src.")
                )
        elif isinstance(node, ast.ImportFrom):
            mod = (node.level, (node.module or "").removeprefix("src."))
            for a in node.names:
                found.setdefault(a.asname or a.name, set()).add((*mod, a.name))
    return {k: frozenset(v) for k, v in found.items()}


def _bare(node: ast.stmt) -> ast.stmt:
    """The statement with every type annotation dropped."""
    for n in ast.walk(node):
        if isinstance(n, ast.arg):
            n.annotation = None
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n.returns = None
        elif isinstance(n, ast.AnnAssign):
            n.annotation = ast.Constant(None)
    return node


def _is_new_test(node: ast.stmt, taken: set[str]) -> bool:
    return (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
        and node.name not in taken
        and not any("fixture" in ast.dump(d) for d in node.decorator_list)
    )


def lock_violations(
    locked: str, new: str, *, extend: bool = False, annotations: bool = False
) -> list[str]:
    """Why `new` may not replace the locked test file; [] when it may.

    Every top-level non-import statement must be identical by `ast.dump`, so no assert, decorator,
    helper, patch or early return can change. `extend` also allows new, undecorated `test*`
    functions (a test file that already existed); `annotations` ignores type annotations (a
    lint/mypy fix). Imports may change, but never rebind a name the locked file already imports.
    """
    try:
        old_tree, new_tree = ast.parse(locked), ast.parse(new)
    except SyntaxError:
        return ["the test file does not parse"]
    prep = _bare if annotations else (lambda n: n)
    old = Counter(ast.dump(prep(n)) for n in _statements(old_tree))
    taken, kept, problems = _defined(old_tree), [], []
    for node in _statements(new_tree):
        if extend and _is_new_test(node, taken):
            taken.add(getattr(node, "name", ""))
        else:
            kept.append(ast.dump(prep(node)))
    if Counter(kept) != old:
        problems.append(
            f"{sum((old - Counter(kept)).values())} locked statement(s) changed or removed, "
            f"{sum((Counter(kept) - old).values())} unexpected"
        )
    elif kept != [ast.dump(prep(n)) for n in _statements(old_tree)]:
        problems.append("locked statements were reordered")
    before, after = _bindings(old_tree), _bindings(new_tree)
    if any(after.get(b) != v for b, v in before.items()):
        problems.append("an import the test file already had was removed or rebound")
    if (set(after) - set(before)) & _defined(old_tree):
        problems.append("a new import shadows a name the tests define")
    return problems


@dataclass(frozen=True)
class Edit:
    """A single SEARCH/REPLACE edit block."""

    search: str
    replace: str


# the model often drops the space or changes the marker length, so accept both
EDIT_BLOCK = re.compile(
    r"^<{5,9} ?SEARCH[ \t]*\n(.*?)^={5,9}[ \t]*\n(.*?)^>{5,9} ?REPLACE[ \t]*$", re.M | re.S
)


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


def _quoted_modules(message: str) -> list[str]:
    return re.findall(r"'([\w.]+)'", message)


def collection_errors(report: str, modules: Collection[str] = ()) -> set[str]:
    """Test files whose own import is at fault. A file whose collection failed because an
    implementation module (`modules`, e.g. `jarvis.new`) lacks a name or is missing is not
    returned: the implementation must change, never the locked test."""
    found: set[str] = set()
    blocks = re.split(r"^_{3,} ERROR collecting (\S+) _{3,}$", report, flags=re.M)
    for rel, raw in zip(blocks[1::2], blocks[2::2], strict=True):
        body = re.split(r"^(?:_{3,} |={3,} )", raw, flags=re.M)[0]
        frames = re.findall(r"^(\S+?):\d+: in ", body, re.M)
        error = re.findall(r"^E\s+(\w*(?:Error|Exception)): (.*)$", body, re.M)
        kind, message = error[-1] if error else ("", "")
        ours = any(
            m == mod or m.endswith("." + mod) for m in _quoted_modules(message) for mod in modules
        )
        if kind in ("ImportError", "ModuleNotFoundError") and ours:
            continue
        if (frames and frames[-1].endswith(rel)) or (
            kind in ("SyntaxError", "IndentationError") and Path(rel).name in body
        ):
            found.add(rel)
    return found


def only_test_errors(report: str, tests: Collection[str]) -> set[str]:
    """Test files holding every ruff/mypy error, when those are the report's only failures."""
    sections = split_report(report)
    failing = re.search(r"^(?:FAILED|ERROR) ", sections.get("PYTEST", ""), re.M)
    paths = {
        m.group(1)
        for key in ("RUFF", "MYPY")
        for line in sections.get(key, "").splitlines()
        if (m := RUFF_LINE.match(line) or MYPY_LINE.match(line))
    }
    return paths if paths and paths <= set(tests) and not failing else set()


def test_names(source: str) -> set[str]:
    """Names of every `test*` function or method in the source (empty when it does not parse)."""
    try:
        nodes = ast.walk(ast.parse(source))
    except SyntaxError:
        return set()
    return {
        n.name
        for n in nodes
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
    }


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
