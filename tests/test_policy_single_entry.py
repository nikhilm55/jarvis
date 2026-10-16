"""The one structural sensor for rule 7: every tool call goes through `gated_dispatch`.

It walks `src/jarvis` and fails when code outside the gate calls the policy deciding functions or
runs a tool implementation by another road. Behaviour is tested elsewhere; this only catches a
new call site that skips the gate.
"""

import ast
from pathlib import Path
from typing import TypeGuard

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"

# The desktop operations a tool performs, and the helper that routes the brain's calls to them.
_OPERATIONS = {"open_app", "close_app", "volume_get", "volume_set", "volume_step", "mute"}
_OPERATIONS |= {"call_desktop"}
_DECIDERS = {"decide", "gate"}
# The implementation layer: it defines or forwards operations and is only reached through a
# `@tool_impl` function (the MCP server's, or the fast path's).
_IMPLEMENTATION_LAYER = (
    "desktop/",
    "brain/desktop_tools.py",
    "brain/dispatch.py",
    "brain/session.py",
    "orchestrator/assemble.py",
)
_GATE = "policy/gated.py"


def _callee(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _is_tool_impl(node: ast.AST) -> TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(_callee_of_decorator(d) == "tool_impl" for d in node.decorator_list)


def _callee_of_decorator(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):  # `@tool_impl("name")`
        return _callee_of_decorator(node.func)
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def violations(source: str, path: str) -> list[str]:
    """Calls in `source` (a module at `path` under src/jarvis) that bypass the gate."""
    tree = ast.parse(source)
    impl_names = {n.name for n in ast.walk(tree) if _is_tool_impl(n)}
    found: list[str] = []
    imported = {  # names this module took from the policy package
        a.asname or a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("jarvis.policy")
        for a in n.names
    }

    def decides(node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in _DECIDERS and func.id in imported
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return func.attr in _DECIDERS and func.value.id in {"policy", "decide", "legacy"}
        return False

    def visit(node: ast.AST, inside_impl: bool) -> None:
        inside = inside_impl or _is_tool_impl(node)
        if isinstance(node, ast.Call):
            name = _callee(node)
            where = f"{path}:{node.lineno}: {name}()"
            if decides(node) and path != _GATE:
                found.append(f"{where} decides outside the gate")
            if isinstance(node.func, ast.Name) and name in impl_names:
                found.append(f"{where} calls a tool implementation directly")
            if name in _OPERATIONS and not inside and not path.startswith(_IMPLEMENTATION_LAYER):
                found.append(f"{where} runs a tool outside gated_dispatch")
            if name == "_dispatch" and not inside and path.startswith("mcp/"):
                found.append(f"{where} dispatches outside a tool implementation")
        for child in ast.iter_child_nodes(node):
            visit(child, inside)

    visit(tree, False)
    return found


def test_should_find_no_call_that_bypasses_gated_dispatch_in_the_product_code() -> None:
    problems: list[str] = []
    for file in sorted(SRC.rglob("*.py")):
        rel = file.relative_to(SRC).as_posix()
        problems += violations(file.read_text(encoding="utf-8"), rel)
    assert problems == []


@pytest.mark.parametrize(
    ("source", "path", "expected"),
    [
        ("async def f(d):\n    return await d.open_app('x')\n", "fastpath/x.py", "outside gated"),
        (
            "from jarvis.policy import decide\ndef f(c, m, x):\n    return decide(c, m, x)\n",
            "fastpath/x.py",
            "decides outside",
        ),
        ("def f(t, a, m):\n    return policy.gate(t, a, m)\n", "mcp/server.py", "decides outside"),
        (
            "async def f(s):\n    return await s._dispatch('n', {})\n",
            "mcp/server.py",
            "outside a tool",
        ),
        (
            "@tool_impl('x')\nasync def run(a):\n    return 1\nasync def f():\n    run(1)\n",
            "mcp/server.py",
            "directly",
        ),
        (
            "async def f(d):\n    return await call_desktop(d, 'n', {})\n",
            "mcp/server.py",
            "outside gated",
        ),
    ],
)
def test_should_flag_a_call_that_routes_around_the_gate(
    source: str, path: str, expected: str
) -> None:
    found = violations(source, path)
    assert found and expected in found[0]


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("@tool_impl('x')\nasync def run(a):\n    return await d.open_app('x')\n", "fastpath/x.py"),
        (
            "from jarvis.policy import decide\ndef f(c, m, x):\n    return decide(c, m, x)\n",
            "policy/gated.py",
        ),
        ("async def f(d):\n    return await d.open_app('x')\n", "desktop/client.py"),
        ("async def f(g):\n    return await gated_dispatch(g)\n", "mcp/server.py"),
    ],
)
def test_should_allow_the_roads_that_go_through_the_gate(source: str, path: str) -> None:
    assert violations(source, path) == []
