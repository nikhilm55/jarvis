"""Pure sensors for the local-model loop: test-weakening guard, SEARCH/REPLACE
edit parsing and applying, failure fingerprint, per-file error routing,
collection-error detection and the git scope check.

Stdlib only: ast, re, dataclasses. No network, no subprocess, no file I/O.
"""

from __future__ import annotations

import ast
import re
import shlex
from collections import Counter
from collections.abc import Collection
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
                # `import a.b` binds the name `a` to module a; `import a.b as c` binds c to a.b
                target = a.name if a.asname else a.name.split(".")[0]
                found.setdefault(a.asname or target, set()).add(
                    (-1, target.removeprefix("src."), "")
                )
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").removeprefix("src.")
            for a in node.names:
                found.setdefault(a.asname or a.name, set()).add((node.level, mod, a.name))
    return {k: frozenset(v) for k, v in found.items()}


Alias = tuple[int, str, str, str]  # (level or -1, module, name, asname): one imported name
# a bare noqa comment, or one that lists F401: ruff --fix leaves such an import alone, so it is
# there on purpose (a fixture, a side-effect import, an imported test)
NOQA = re.compile(r"#\s*noqa(?![\w])(?::\s*(?P<codes>[\w, ]+))?", re.IGNORECASE)


def _aliases(node: ast.stmt) -> set[Alias]:
    if isinstance(node, ast.Import):
        return {(-1, a.name.removeprefix("src."), "", a.asname or "") for a in node.names}
    if isinstance(node, ast.ImportFrom):
        mod = (node.module or "").removeprefix("src.")
        return {(node.level, mod, a.name, a.asname or "") for a in node.names}
    return set()


def _kept_on_purpose(source: str, tree: ast.Module) -> set[Alias]:
    """The imported names on lines carrying a noqa that ruff honours for F401."""
    keep = _noqa_lines(source)
    return {a for n in tree.body if _on_a_kept_line(n, keep) for a in _aliases(n)}


def _bound_name(alias: Alias) -> str:
    level, module, name, asname = alias
    return asname or (module.split(".")[0] if level == -1 else name)


def _import_problem(
    locked: str, new: str, trees: tuple[ast.Module, ast.Module], rename: tuple[Collection[str], ...]
) -> bool:
    """A locked import was dropped while in use, or rebound, or one kept on purpose is gone. An
    import nothing uses may go (ruff --fix), but a `test*` / `Test*` name is collected by pytest
    and a `# noqa` import is a fixture or a side effect: neither is ever "unused". An import kept
    on purpose must keep its noqa too (or be used by name): a comment is invisible to the AST, and
    ruff --fix deletes the import once the noqa is gone."""
    old_tree, new_tree = trees
    before, after = _bindings(old_tree), _bindings(new_tree)
    used = _used_names(new_tree)
    changed = {
        b
        for b, v in before.items()
        if b in after and after[b] != v and _renamed(v, after[b], *rename)
    }
    now_kept = _kept_on_purpose(new, new_tree)
    present = {
        a for n in new_tree.body for a in _aliases(n) if a in now_kept or _bound_name(a) in used
    }
    renamed_names = {n for b in changed for _, _, n in before[b]}
    purposeful = {a for a in _kept_on_purpose(locked, old_tree) if a[2] not in renamed_names}
    return (
        not purposeful <= present
        or any(b in used or b.startswith(("test", "Test")) for b in before if b not in after)
        or any(after[b] != v and b not in changed for b, v in before.items() if b in after)
    )


def _used_names(tree: ast.Module) -> set[str]:
    """Every name the file reads, including a test's parameter names (a fixture is used by name)."""
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)
    }


def _noqa_lines(source: str) -> set[int]:
    """The (1-based) lines carrying a noqa comment that ruff honours for F401."""
    found: set[int] = set()
    for number, line in enumerate(source.splitlines(), start=1):
        for m in NOQA.finditer(line):
            if m.group("codes") is None or "F401" in m.group("codes").upper():
                found.add(number)
    return found


def _on_a_kept_line(stmt: ast.stmt, keep: set[int]) -> bool:
    return any(n in keep for n in range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))


def _prune_unused_imports(node: ast.stmt, keep: set[int]) -> ast.stmt:
    """Drop, inside every function body, the imports whose name that function never uses (what
    `ruff --fix` removes), so removing one is not a change to the statement. A used import stays,
    and so does one on a `keep` line (a noqa import is there on purpose)."""
    for func in (
        n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        used = _used_names(ast.Module(body=[func], type_ignores=[]))
        for block in [n for n in ast.walk(func) if hasattr(n, "body")]:
            for field in ("body", "orelse", "finalbody"):
                stmts = getattr(block, field, None)
                if not isinstance(stmts, list):
                    continue
                for stmt in stmts:
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)) and not _on_a_kept_line(
                        stmt, keep
                    ):
                        stmt.names = [a for a in stmt.names if _bound(a) in used or a.name == "*"]
                kept = [
                    s
                    for s in stmts
                    if not (isinstance(s, (ast.Import, ast.ImportFrom)) and not s.names)
                ]
                setattr(block, field, kept or [ast.Pass()])
    return node


def _bound(alias: ast.alias) -> str:
    return alias.asname or alias.name.split(".")[0]


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


ALLOWED_STORES = re.compile(
    r"os\.environ\[[^\]]+\]|sys\.(?:stdout|stderr|stdin)|logging(?:\.root)?\.\w+"
)


def _stores(tree: ast.AST, names: set[str], allowed: bool = False) -> list[str]:
    """Each assignment to (or deletion of) an attribute or item of one of `names`, as source text
    such as `sys.modules['x']`. `allowed` skips os.environ, sys.stdout/stderr/stdin and logging."""
    found: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        elif isinstance(n, ast.Delete):
            targets = n.targets
        else:
            continue
        for target in targets:
            for sub in ast.walk(target):
                root = sub
                while isinstance(root, (ast.Attribute, ast.Subscript)):
                    root = root.value
                text = ast.unparse(sub)
                if root is sub or not isinstance(root, ast.Name) or root.id not in names:
                    continue
                if not (allowed and ALLOWED_STORES.fullmatch(text)):
                    found.append(text)
                break
    return found


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
        and not _stores(node, names | {"sys", "builtins"})
    )


def _renamed(
    old: frozenset[Binding],
    new: frozenset[Binding],
    modules: Collection[str],
    culprits: Collection[str],
) -> bool:
    """A from-import whose module path was corrected to a manifest module, names unchanged, and
    only the statement the collection error named (`culprits`: its module or an imported name)."""
    if not new or any(level != 0 for level, _, _ in (*old, *new)):
        return False
    named = any(mod in culprits or name in culprits for _, mod, name in old)
    inside = all(any(mod == m or mod.endswith("." + m) for m in modules) for _, mod, _ in new)
    return named and inside and {n for _, _, n in old} == {n for _, _, n in new}


def lock_violations(
    locked: str,
    new: str,
    *,
    extend: bool = False,
    annotations: bool = False,
    rename: tuple[Collection[str], Collection[str]] = ((), ()),
) -> list[str]:
    """Why `new` may not replace the locked test file; [] when it may.

    Every top-level non-import statement must be identical by `ast.dump`, so no assert, decorator,
    helper, patch or early return can change. `extend` also allows new tests appended after the
    last locked statement (see `_is_new_test`); `annotations` ignores type annotations (a lint/mypy
    fix). Imports may change, but never rebind a name the locked file already imports (except to
    correct a module path to a manifest module, in the one statement the collection error names:
    `rename` is (manifest modules, names the error quotes)), and `import *` is never allowed.
    """
    try:
        old_tree, new_tree = ast.parse(locked), ast.parse(new)
    except SyntaxError:
        return ["the test file does not parse"]
    old_keep, new_keep = _noqa_lines(locked), _noqa_lines(new)

    def prep(n: ast.stmt, keep: set[int]) -> ast.stmt:
        return _prune_unused_imports(_bare(n) if annotations else n, keep)

    old = Counter(ast.dump(prep(n, old_keep)) for n in _statements(old_tree))
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
            kept.append(ast.dump(prep(node, new_keep)))
            if added and not problems:
                problems.append("a new test sits before a locked statement; append them last")
    if Counter(kept) != old:
        problems.append(
            f"{sum((old - Counter(kept)).values())} locked statement(s) changed or removed, "
            f"{sum((Counter(kept) - old).values())} unexpected"
        )
    elif kept != [ast.dump(prep(n, old_keep)) for n in _statements(old_tree)]:
        problems.append("locked statements were reordered")
    # An import may move, merge, split or be re-sorted (the formatter and ruff --fix do), and an
    # import nothing uses may go; but a name must stay bound to the same target while it is used.
    if _import_problem(locked, new, (old_tree, new_tree), rename):
        problems.append("an import the test file already had was removed or rebound")
    if (set(after) - set(before)) & _defined(old_tree):
        problems.append("a new import shadows a name the tests define")
    if any(
        isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
        for n in ast.walk(new_tree)
    ):
        problems.append("`import *` is not allowed in a test file")
    return problems


SKIP_ESCAPES = ("os._exit", "sys.exit", "unittest.SkipTest", "pytest.skip", "pytest.xfail")
TAMPER_MODULES = ("pytest", "_pytest", "builtins", "atexit", "signal")


def tamper_violations(source: str) -> list[str]:
    """A cheap deterrent, not a sandbox: how an implementation file reaches the test machinery.
    Each message names its exact target, so one kind can never hide another. Flagged: importing
    pytest, _pytest, unittest.mock, builtins, atexit or signal; os._exit and sys.exit; SkipTest
    and pytest.skip/xfail (a skip hides a failure from the summary check); dynamic
    import, exec and eval; assigning into an imported module, `sys.modules` or `builtins`
    (os.environ, sys.stdout/stderr/stdin and logging are fine)."""
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
            found = [(f"{n.module or ''}.{a.name}".strip("."), a.asname or a.name) for a in n.names]
        for full, name in found:
            bound.add(name)
            if (
                full.split(".")[0] in TAMPER_MODULES
                or full.startswith("unittest.mock")
                or full in ("os._exit", "sys.exit", "unittest.SkipTest")
            ):
                problems.append(f"imports {full}")
        if isinstance(n, ast.Call):
            called = getattr(n.func, "id", getattr(n.func, "attr", ""))
            if called in ("__import__", "import_module", "exec", "eval"):
                problems.append(f"calls {called}()")
        if isinstance(n, ast.Attribute) and ast.unparse(n) in SKIP_ESCAPES:
            problems.append(f"uses {ast.unparse(n)}")
        if isinstance(n, ast.Name) and n.id == "SkipTest":
            problems.append("uses SkipTest")
    problems += [f"stores into {t}" for t in _stores(tree, bound, allowed=True)]
    return sorted(set(problems))


CLEAN_MSG = "pytest did not report a clean summary"


def pytest_clean(output: str, minimum: int = 0, skips: int = 0) -> bool:
    """Is pytest's last line a summary like `5 passed in 0.1s`, with nothing failed or in error,
    at least `minimum` passed, and no more skipped/xfailed than the locked tests' own `skips`?
    The exit code alone can be forged (atexit, os._exit), and a skip hides a failure."""
    lines = output.strip().splitlines()
    last = lines[-1] if lines else ""
    if not re.search(r" in [\d.]+s\b", last):
        return False
    counts = {word: int(n) for n, word in re.findall(r"(\d+) (\w+)", last)}
    broken = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    skipped = counts.get("skipped", 0) + counts.get("xfailed", 0)
    return counts.get("passed", 0) >= max(minimum, 1) and not broken and skipped <= skips


def quiet_addopts(addopts: str) -> str:
    """A repo's pytest addopts without its verbosity flags (-q, -qq, -v, --quiet, ...), so the
    loop can add exactly one -q: two of them (-qq) drop the summary line pytest_clean reads."""
    drop = re.compile(r"-[qv]+|--quiet|--verbose")
    return shlex.join(t for t in shlex.split(addopts) if not drop.fullmatch(t))


def collectable_tests(source: str) -> int:
    """A lower bound on what pytest collects: top-level `test*` functions and the methods of
    `Test*` classes, less the skip markers (parametrize can only add to it)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)

    def tests(body: list[ast.stmt]) -> int:
        return sum(isinstance(n, funcs) and n.name.startswith("test") for n in body)

    classes = [
        c.body for c in tree.body if isinstance(c, ast.ClassDef) and c.name.startswith("Test")
    ]
    stats = test_stats(source)
    return max(0, tests(tree.body) + sum(tests(b) for b in classes) - (stats.skips if stats else 0))


def req_number(text: str) -> str | None:
    """`1`, `requirement 2`, `R3.` -> the number; None when the text has none."""
    m = re.match(r"\D*(\d+)", text)
    return m.group(1) if m else None


def plan_distinct(pairs: list[tuple[str, str]], required: list[str]) -> bool:
    """Plan (requirement, test) pairs: with two or more requirements, each must have a test
    that is not the one test named for every requirement."""
    by: dict[str, set[str]] = {}
    for req, test in pairs:
        if (n := req_number(req)) is not None:
            by.setdefault(n, set()).add(test)
    reqs = [r for r in (required or sorted(by)) if r in by]
    if len(reqs) < 2:
        return True
    common = set.intersection(*(by[r] for r in reqs))
    return all(by[r] - common for r in reqs)


def review_covers(reviewed: list[str], required: list[str], plan_requirements: int) -> bool:
    """Do the review's items cover every numbered brief requirement (distinct numbers), or, with
    no numbered requirements, at least as many distinct items as the plan has requirements?"""
    if required:
        return set(required) <= {n for r in reviewed if (n := req_number(r)) is not None}
    return len(set(reviewed)) >= max(1, plan_requirements)


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
    """The lines of each section that concern `rel`; pytest's FAILED/ERROR summaries and a TIMEOUT
    line (it names no file, and the model must see the tests hang) always stay."""
    routed: dict[str, str] = {}
    for key, body in split_report(report).items():
        summary = key == "PYTEST"
        kept = [
            line
            for line in body.splitlines()
            if rel in line
            or (
                summary
                and (line.startswith(("FAILED ", "ERROR ", "TIMEOUT:")) or CLEAN_MSG in line)
            )
        ]
        if kept:
            routed[key] = "\n".join(kept)
    return routed


def _quoted_modules(message: str) -> list[str]:
    return re.findall(r"'([\w.]+)'", message)


def _collect_blocks(report: str) -> dict[str, tuple[list[str], str, str]]:
    """Each `ERROR collecting <file>` block: its traceback frames' files, error type, message."""
    blocks = re.split(r"^_{3,} ERROR collecting (\S+) _{3,}$", report, flags=re.M)
    found = {}
    for rel, raw in zip(blocks[1::2], blocks[2::2], strict=True):
        body = re.split(r"^(?:_{3,} |={3,} )", raw, flags=re.M)[0]
        error = re.findall(r"^E\s+(\w*(?:Error|Exception)): (.*)$", body, re.M)
        kind, message = error[-1] if error else ("", "")
        found[rel] = (re.findall(r"^(\S+?):\d+: in ", body, re.M), kind, message)
    return found


def collection_errors(report: str, modules: Collection[str] = ()) -> set[str]:
    """Test files whose own import is at fault. A file whose collection failed because an
    implementation module (`modules`, e.g. `jarvis.new`) lacks a name or is missing is not
    returned: the implementation must change, never the locked test."""
    found: set[str] = set()
    for rel, (frames, kind, message) in _collect_blocks(report).items():
        ours = any(
            m == mod or m.endswith("." + mod) for m in _quoted_modules(message) for mod in modules
        )
        if kind in ("ImportError", "ModuleNotFoundError") and ours:
            continue
        if (frames and frames[-1].endswith(rel)) or kind in ("SyntaxError", "IndentationError"):
            found.add(rel)
    return found


def collection_culprits(report: str, rel: str) -> set[str]:
    """The names a collection error quotes for `rel` (e.g. the missing module `jarvis.helpres`)."""
    return set(_quoted_modules(_collect_blocks(report).get(rel, ([], "", ""))[2]))


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
