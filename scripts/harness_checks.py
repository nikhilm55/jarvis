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


Binding = tuple[int, str, str]  # (relative level or -1 for `import x`, module, imported name)


def _bindings(tree: ast.Module) -> dict[str, frozenset[Binding]]:
    """What each top-level import binds, with a leading `src.` ignored."""
    found: dict[str, set[Binding]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                key = (a.asname or a.name).split(".")[0]
                found.setdefault(key, set()).add((-1, a.name.removeprefix("src."), ""))
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").removeprefix("src.")
            for a in node.names:
                found.setdefault(a.asname or a.name, set()).add((node.level, mod, a.name))
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


BAD_MARKS = ("skip", "xfail", "usefixtures", "filterwarnings")
TRICKS = (
    "globals",
    "locals",
    "vars",
    "setattr",
    "delattr",
    "exec",
    "eval",
    "__import__",
    "compile",
)


def _stores_into(tree: ast.AST, names: set[str]) -> bool:
    """Does the code assign to (or delete) an attribute or item of one of `names`?"""
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        elif isinstance(n, ast.Delete):
            targets = n.targets
        else:
            continue
        for sub in (s for t in targets for s in ast.walk(t)):
            root = sub
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if root is not sub and isinstance(root, ast.Name) and root.id in names:
                return True
    return False


def _mark_ok(dec: ast.expr) -> bool:
    """`@pytest.mark.<name>` or `@pytest.mark.<name>(...)`, but never skip/xfail/usefixtures."""
    call = dec.func if isinstance(dec, ast.Call) else dec
    mark = call.value if isinstance(call, ast.Attribute) else None
    return (
        isinstance(call, ast.Attribute)
        and call.attr not in BAD_MARKS
        and isinstance(mark, ast.Attribute)
        and mark.attr == "mark"
        and isinstance(mark.value, ast.Name)
        and mark.value.id == "pytest"
    )


def _is_new_test(node: ast.stmt, names: set[str]) -> bool:
    """A plain new `def test_*` whose decorators are pytest marks and whose body cannot reach
    out of the test (no globals(), setattr, `global`, or stores into module-level objects)."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    inside = list(ast.walk(node))
    return (
        node.name.startswith("test")
        and node.name not in names
        and all(_mark_ok(d) for d in node.decorator_list)
        and not any(isinstance(n, ast.Global) for n in inside)
        and not any(isinstance(n, ast.Name) and n.id in TRICKS for n in inside)
        and not any(
            isinstance(n, ast.Attribute) and n.attr in ("modules", "__dict__") for n in inside
        )
        and not _stores_into(node, names | {"sys", "builtins"})
    )


def _renamed(old: frozenset[Binding], new: frozenset[Binding], modules: Collection[str]) -> bool:
    """A from-import whose module path was corrected to a manifest module, names unchanged."""
    if not new or any(level != 0 for level, _, _ in (*old, *new)):
        return False
    inside = all(any(mod == m or mod.endswith("." + m) for m in modules) for _, mod, _ in new)
    return inside and {n for _, _, n in old} == {n for _, _, n in new}


def lock_violations(
    locked: str,
    new: str,
    *,
    extend: bool = False,
    annotations: bool = False,
    modules: Collection[str] = (),
) -> list[str]:
    """Why `new` may not replace the locked test file; [] when it may.

    Every top-level non-import statement must be identical by `ast.dump`, so no assert, decorator,
    helper, patch or early return can change. `extend` also allows new tests appended after the
    last locked statement (see `_is_new_test`); `annotations` ignores type annotations (a lint/mypy
    fix). Imports may change, but never rebind a name the locked file already imports (except to
    correct a module path to one of `modules`, the implementation), and `import *` is never allowed.
    """
    try:
        old_tree, new_tree = ast.parse(locked), ast.parse(new)
    except SyntaxError:
        return ["the test file does not parse"]
    prep = _bare if annotations else (lambda n: n)
    old = Counter(ast.dump(prep(n)) for n in _statements(old_tree))
    before, after = _bindings(old_tree), _bindings(new_tree)
    names = _defined(old_tree) | set(before) | set(after)
    kept: list[str] = []
    problems: list[str] = []
    added = False
    for node in _statements(new_tree):
        if extend and _is_new_test(node, names):
            names.add(getattr(node, "name", ""))
            added = True
        else:
            kept.append(ast.dump(prep(node)))
            if added and not problems:
                problems.append("a new test sits before a locked statement; append them last")
    if Counter(kept) != old:
        problems.append(
            f"{sum((old - Counter(kept)).values())} locked statement(s) changed or removed, "
            f"{sum((Counter(kept) - old).values())} unexpected"
        )
    elif kept != [ast.dump(prep(n)) for n in _statements(old_tree)]:
        problems.append("locked statements were reordered")
    if any(
        after.get(b) != v and not _renamed(v, after.get(b, frozenset()), modules)
        for b, v in before.items()
    ):
        problems.append("an import the test file already had was removed or rebound")
    if (set(after) - set(before)) & _defined(old_tree):
        problems.append("a new import shadows a name the tests define")
    if any(
        isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
        for n in ast.walk(new_tree)
    ):
        problems.append("`import *` is not allowed in a test file")
    return problems


def tamper_violations(source: str) -> list[str]:
    """How an implementation file reaches the test machinery: it must not import pytest, _pytest,
    unittest.mock or builtins, dynamic-import or exec, or assign into an imported module,
    `sys.modules` or `builtins` (e.g. `_pytest.python.Function.runtest = ...`)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    problems: list[str] = []
    bound = {"sys", "builtins"}
    for n in ast.walk(tree):
        found = []
        if isinstance(n, ast.Import):
            found = [(a.name, a.asname or a.name.split(".")[0]) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            found = [(f"{n.module or ''}.{a.name}", a.asname or a.name) for a in n.names]
        for full, name in found:
            bound.add(name)
            if full.split(".")[0] in ("pytest", "_pytest", "builtins") or full.startswith(
                "unittest.mock"
            ):
                problems.append(f"imports {full.strip('.')}")
        if isinstance(n, ast.Call):
            called = getattr(n.func, "id", getattr(n.func, "attr", ""))
            if called in ("__import__", "import_module", "exec", "eval"):
                problems.append(f"calls {called}()")
    if _stores_into(tree, bound):
        problems.append("assigns into an imported module, sys.modules or builtins")
    return sorted(set(problems))


def brief_requirements(spec: str) -> list[str]:
    """Numbers of the numbered lines under a `## Requirements` heading ([] without one)."""
    section = re.search(
        r"^#{1,6}[ \t]*Requirements[ \t]*$(.*?)(?=^#{1,6}[ \t]|\Z)", spec, re.M | re.S | re.I
    )
    return re.findall(r"^[ \t]*(\d+)\.", section.group(1), re.M) if section else []


@dataclass(frozen=True)
class Edit:
    """A SEARCH/REPLACE block. A malformed one carries `error` and is never applied."""

    search: str
    replace: str
    error: str = ""


# the model often drops the space or changes the marker length, so accept both
SEARCH_MARK = re.compile(r"<{5,9} ?SEARCH")
DIVIDER = re.compile(r"={5,9}")
REPLACE_MARK = re.compile(r">{5,9} ?REPLACE")


def _text(lines: list[str]) -> str:
    return "".join(f"{x}\n" for x in lines)


def parse_edits(reply: str) -> list[Edit]:
    """Aider-style blocks (CRLF too). A block with a stray marker line inside its SEARCH or
    REPLACE text, or one that never closes, becomes an Edit with `error`; text between blocks
    is ignored."""
    edits: list[Edit] = []
    search: list[str] | None = None  # set while inside a block
    replace: list[str] | None = None
    error = ""
    for line in reply.replace("\r\n", "\n").split("\n"):
        mark = line.rstrip()
        if SEARCH_MARK.fullmatch(mark):
            if search is not None:
                edits.append(Edit("", "", "unterminated block (a marker line is inside it)"))
            search, replace, error = [], None, ""
        elif search is None:
            continue
        elif DIVIDER.fullmatch(mark):
            if replace is None:
                replace = []
            else:
                error = "SEARCH or REPLACE contains a marker line"
        elif REPLACE_MARK.fullmatch(mark):
            error = error or (
                "" if replace is not None else "no ======= between SEARCH and REPLACE"
            )
            edits.append(Edit(_text(search), _text(replace or []), error))
            search = replace = None
        else:
            (search if replace is None else replace).append(line)
    if search is not None:
        edits.append(Edit("", "", "unterminated block"))
    return edits


def apply_edits(content: str, edits: list[Edit]) -> tuple[str, list[str]]:
    """Apply *edits* in order to *content*; return (new_content, errors)."""
    errors: list[str] = []
    for idx, edit in enumerate(edits, start=1):
        if edit.error:
            errors.append(f"edit {idx}: {edit.error}")
            continue
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
