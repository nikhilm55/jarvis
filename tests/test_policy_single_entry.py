"""The one structural sensor for rule 7: every tool call goes through `gated_dispatch`.

It parses `src/jarvis` and flags every way found so far of reaching a tool without the gate:
calling `decide`/`gate`, calling a `@tool_impl` function (by name, alias or from a table),
reading or building the impl table (`impls`), calling `.dispatch(`, using a `TurnTools`, and
touching a desktop operation or `call_desktop` outside a `@tool_impl` function.

There is no exempt file. A line that must do one of these carries `# gate-ok: <reason>`; the
test lists every marker, so adding one is a visible, reviewed change.
"""

# ruff: noqa: E501  (the bypass shapes below are one-line sources; wrapping them hides the shape)
import ast
import io
import re
import tokenize
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
GATE = "policy/gated.py"

_OPERATIONS = frozenset(
    {"open_app", "close_app", "volume_get", "volume_set", "volume_step", "mute"}
)
_DECIDERS = frozenset({"decide", "gate"})
_DISPATCHES = frozenset({"dispatch", "_dispatch"})
_MARKER = re.compile(r"#\s*gate-ok:\s*(\S.*?)\s*$")

# Every `# gate-ok` in the product, with how many lines carry it. Edit with a reviewer's eye.
EXPECTED_MARKERS: Counter[tuple[str, str]] = Counter(
    {
        ("desktop/worker.py", "worker runs the op"): 6,
        ("brain/desktop_tools.py", "via MCP impl"): 6,
        ("brain/dispatch.py", "via MCP impl"): 2,
        ("brain/session.py", "via MCP impl"): 2,
        ("orchestrator/assemble.py", "late-bound brain hook"): 1,
        ("fastpath/executor.py", "builds the impl table"): 1,
        ("mcp/server.py", "builds the impl table"): 1,
    }
)


@dataclass
class Scan:
    findings: list[str] = field(default_factory=list)
    used: list[tuple[int, str]] = field(default_factory=list)  # (line, reason) of honoured markers
    marked: dict[int, str] = field(default_factory=dict)  # every marker found, by line


def _is_impl(node: ast.AST) -> TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(_callee(d) == "tool_impl" for d in node.decorator_list)


def _callee(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return _callee(node.func)
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _targets(node: ast.Assign | ast.AnnAssign) -> list[str]:
    raw = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [n for t in raw if (n := _callee(t))]


def _markers(source: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT and (m := _MARKER.search(tok.string)):
            found[tok.start[0]] = m.group(1)
    return found


def _collect(tree: ast.Module, impls: set[str]) -> set[str]:
    """Names of `TurnTools` handlers in this module; grows `impls` with aliases of impls."""
    handlers: set[str] = set()
    for _ in range(3):  # a few passes settle `a = TurnTools(); b = a; c = b`
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value, names = node.value, _targets(node)
            if isinstance(node, ast.AnnAssign) and "TurnTools" in ast.unparse(node.annotation):
                handlers.update(names)
            if value is not None and _callee(value) in {"TurnTools", *handlers}:
                handlers.update(names)
            if isinstance(value, ast.Name) and value.id in impls:
                impls.update(names)
    return handlers


def scan(source: str, path: str, impl_names: frozenset[str] = frozenset()) -> Scan:
    """Every way `source` (a module at `path` under src/jarvis) reaches a tool outside the gate."""
    tree = ast.parse(source)
    result = Scan(marked=_markers(source))
    impls = {n.name for n in ast.walk(tree) if _is_impl(n)}
    impls |= {  # an impl from another module counts where this one imports it (under any name)
        a.asname or a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
        if a.name in impl_names
    }
    handlers = _collect(tree, impls)

    statement = [0, 0]  # line range of the innermost simple statement being visited

    def flag(node: ast.AST, what: str) -> None:
        """Record a finding unless a marker sits on a line of the statement it is in."""
        line = getattr(node, "lineno", 0)
        lo, hi = (
            (statement[0], statement[1]) if statement[0] <= line <= statement[1] else (line, line)
        )
        marks = [m for m in range(lo, hi + 1) if m in result.marked]
        if marks:
            result.used.append((marks[0], result.marked[marks[0]]))
        else:
            result.findings.append(f"{path}:{line}: {what}")

    def check_call(node: ast.Call, inside: bool) -> None:
        func, name = node.func, _callee(node.func)
        if name in _DECIDERS and path != GATE and _decides(node, tree):
            flag(node, f"{name}() decides outside the gate")
        if isinstance(func, ast.Attribute) and name in _DISPATCHES and not inside:
            flag(node, f".{name}() dispatches outside a tool implementation")
        if name == "TurnTools" or (name in handlers and not inside):
            flag(node, f"{name}() uses a TurnTools turn handler")
        if isinstance(func, ast.Name) and func.id in impls:
            flag(node, f"{func.id}() calls a tool implementation directly")
        if isinstance(func, ast.Subscript) or (
            isinstance(func, ast.Call) and _callee(func.func) in {"get", "pop", "setdefault"}
        ):
            flag(node, "calls a function taken out of a table")
        if path != GATE and any(k.arg == "impls" for k in node.keywords):
            flag(node, "builds the impl table (impls=...) outside the gate")
        if name == "TurnContext" and len(node.args) >= 6:
            flag(node, "builds the impl table (6th TurnContext argument) outside the gate")

    def visit(node: ast.AST, inside_impl: bool) -> None:
        inside = inside_impl or _is_impl(node)
        if isinstance(node, ast.stmt) and not hasattr(node, "body"):
            statement[:] = [node.lineno, node.end_lineno or node.lineno]
        if isinstance(node, ast.Call):
            check_call(node, inside)
        elif isinstance(node, ast.Attribute):
            if node.attr == "impls" and path != GATE:
                flag(node, "reads or sets .impls outside the gate")
            if node.attr in _OPERATIONS and not inside:
                flag(node, f".{node.attr} (a tool operation) used outside gated_dispatch")
        elif isinstance(node, ast.Name) and node.id == "call_desktop" and not inside:
            flag(node, "call_desktop used outside gated_dispatch")
        elif isinstance(node, ast.ImportFrom) and any(a.name == "call_desktop" for a in node.names):
            flag(node, "call_desktop imported outside gated_dispatch")
        for child in ast.iter_child_nodes(node):
            visit(child, inside)

    visit(tree, False)
    return result


def _decides(node: ast.Call, tree: ast.Module) -> bool:
    """`decide(...)` taken from the policy package, or `policy.gate(...)` and the like."""
    imported = {
        a.asname or a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("jarvis.policy")
        for a in n.names
    }
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in imported
    return isinstance(func, ast.Attribute) and _callee(func.value) in {"policy", "decide", "legacy"}


def _product() -> dict[str, str]:
    return {f.relative_to(SRC).as_posix(): f.read_text(encoding="utf-8") for f in SRC.rglob("*.py")}


def _impl_names(sources: dict[str, str]) -> frozenset[str]:
    """Module-level `@tool_impl` functions: the ones another module can import."""
    return frozenset(
        n.name for text in sources.values() for n in ast.parse(text).body if _is_impl(n)
    )


def test_should_find_no_call_that_bypasses_gated_dispatch_in_the_product_code() -> None:
    sources = _product()
    names = _impl_names(sources)
    problems: list[str] = []
    for path, text in sorted(sources.items()):
        problems += scan(text, path, names).findings
    assert problems == []


def test_should_list_every_gate_ok_marker_and_keep_none_that_is_stale() -> None:
    sources = _product()
    names = _impl_names(sources)
    used: Counter[tuple[str, str]] = Counter()
    for path, text in sources.items():
        result = scan(text, path, names)
        assert set(result.marked) == {line for line, _ in result.used}, f"stale marker in {path}"
        used.update((path, reason) for _, reason in result.used)
    assert used == EXPECTED_MARKERS


@pytest.mark.parametrize(
    ("source", "path", "expected"),
    [
        # aliasing a bound method, with or without calling it
        ("def f(d):\n    g = d.open_app\n    return g('x')\n", "brain/new.py", "tool operation"),
        ("def f(d):\n    return map(d.mute, [True])\n", "orchestrator/new.py", "tool operation"),
        # importing the helper under another name, or using it
        ("from jarvis.brain.desktop_tools import call_desktop as cd\n", "mcp/new.py", "imported"),
        ("async def f(d):\n    return await call_desktop(d, 'n', {})\n", "mcp/server.py", "used"),
        # the brain's dispatch, and a TurnTools built or called by a new caller
        (
            "async def f(b):\n    return await b.dispatch('desktop.close_app', {})\n",
            "x.py",
            "dispatches",
        ),
        ("def f(h):\n    return TurnTools('t', h, None, 3)\n", "orchestrator/new.py", "TurnTools"),
        (
            "async def f(h):\n    t = TurnTools('t', h, None, 3)\n    u = t\n    return await u('n', {})\n",
            "orchestrator/new.py",
            "TurnTools",
        ),
        # building or reading the impl table
        ("def f(c, i):\n    return TurnContext('t', impls=i)\n", "orchestrator/new.py", "impls="),
        ("def f(c, i):\n    return replace(c, impls=i)\n", "mcp/new.py", "impls="),
        ("def f(a, b, c, d, e, i):\n    return TurnContext(a, b, c, d, e, i)\n", "x.py", "6th"),
        ("async def f(c):\n    return await c.impls['n']({})\n", "x.py", ".impls"),
        # a tool implementation called by name, by alias, or out of a table
        (
            "@tool_impl('x')\nasync def run(a):\n    return 1\n\nasync def f():\n    run(1)\n",
            "x.py",
            "directly",
        ),
        (
            "@tool_impl('x')\nasync def run(a):\n    return 1\n\ndef f():\n    g = run\n    g(1)\n",
            "x.py",
            "directly",
        ),
        (
            "@tool_impl('x')\nasync def run(a):\n    return 1\n\nasync def f():\n    d = {'a': run}\n    await d['a'](1)\n",
            "x.py",
            "table",
        ),
        ("async def f(d, k):\n    return await d.get(k)({})\n", "x.py", "table"),
        # the old whole-file exemptions: a new unmarked call is flagged in each of those files
        (
            "async def f(d):\n    return await d.open_app('x')\n",
            "brain/session.py",
            "tool operation",
        ),
        (
            "async def f(d):\n    return await d.close_app('x')\n",
            "brain/dispatch.py",
            "tool operation",
        ),
        (
            "async def f(d):\n    return await d.mute(True)\n",
            "orchestrator/assemble.py",
            "tool operation",
        ),
        (
            "async def f(d):\n    return await d.volume_set(5)\n",
            "desktop/worker.py",
            "tool operation",
        ),
        ("async def f(s):\n    return await s._dispatch('n', {})\n", "mcp/server.py", "dispatches"),
        # the M1 gate's roads
        (
            "from jarvis.policy import decide\ndef f(c, m, x):\n    return decide(c, m, x)\n",
            "x.py",
            "decides",
        ),
        ("def f(t, a, m):\n    return policy.gate(t, a, m)\n", "mcp/server.py", "decides"),
    ],
)
def test_should_flag_a_call_that_routes_around_the_gate(
    source: str, path: str, expected: str
) -> None:
    found = scan(source, path).findings
    assert found, source
    assert any(expected in f for f in found), found


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("@tool_impl('n')\nasync def run(a):\n    return await d.open_app('x')\n", "fastpath/x.py"),
        (
            "@tool_impl('n')\nasync def run(a):\n    return await self._dispatch('n', a)\n",
            "mcp/x.py",
        ),
        ("from jarvis.policy import decide\ndef f(c, m, x):\n    return decide(c, m, x)\n", GATE),
        ("def f(c):\n    return c.impls.get('n')\n", GATE),
        ("async def f(g):\n    return await gated_dispatch(g)\n", "mcp/server.py"),
        (
            "class DesktopClient:\n    async def open_app(self, q):\n        return 1\n",
            "desktop/client.py",
        ),
        (
            "def f(c, i):\n    return replace(c, impls=i)  # gate-ok: builds the impl table\n",
            "x.py",
        ),
    ],
)
def test_should_allow_the_roads_that_go_through_the_gate(source: str, path: str) -> None:
    assert scan(source, path).findings == []


def test_should_not_honour_a_marker_without_a_reason() -> None:
    source = "def f(d):\n    return d.mute(True)  # gate-ok:\n"
    assert scan(source, "x.py").findings


def test_should_report_a_marker_that_hides_nothing_as_stale() -> None:
    result = scan("x = 1  # gate-ok: nothing here\n", "x.py")
    assert result.marked == {1: "nothing here"}
    assert result.used == []
