"""The window and app tools through the backend, the worker's JSON lines and the client."""

import asyncio
import contextlib
import io
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.desktop.apps import AppEntry
from jarvis.desktop.backend import DesktopBackend, Hooks
from jarvis.desktop.client import DesktopClient, DesktopError
from jarvis.desktop.windows import Rect, XPort
from jarvis.desktop.worker import serve
from jarvis.desktop.x11 import X11Error
from tests.x_fake import FakeX


def _calc() -> AppEntry:
    return AppEntry(
        "org.example.Calculator.desktop",
        "Calculator",
        "",
        (),
        "calc",
        "Calc",
        Path("/x/calc.desktop"),
    )


def _backend(fake: FakeX | None = None, *, port_error: X11Error | None = None) -> DesktopBackend:
    @contextlib.contextmanager
    def port() -> Iterator[XPort]:
        if port_error is not None:
            raise port_error
        assert fake is not None
        yield fake

    return DesktopBackend(
        Hooks(entries=lambda: [_calc()], windows=lambda: [], port=port, sleep=lambda _s: None)
    )


def _fake() -> FakeX:
    fake = FakeX()
    fake.add(0x10, "Notes", "editor")
    fake.add(0x20, "Calculator", "calc", Rect(50, 50, 300, 400))
    fake.active = 0x20
    return fake


def _call(backend: DesktopBackend, tool: str, /, **args: object) -> dict[str, Any]:
    out = io.StringIO()
    serve(backend, [json.dumps({"id": 1, "op": tool, "args": args})], out)
    reply: dict[str, Any] = json.loads(out.getvalue())
    return reply


def test_should_list_windows_with_their_app_name_and_id() -> None:
    reply = _call(_backend(_fake()), "list_windows")
    assert reply["ok"] is True
    assert reply["result"]["windows"] == [
        {
            "ref": "x11:0x20",
            "title": "Calculator",
            "app": "Calculator",
            "app_id": "org.example.Calculator.desktop",
            "monitor": 0,
            "state": ["focused"],
        },
        {
            "ref": "x11:0x10",
            "title": "Notes",
            "app": "Editor",  # no launcher matches: the WM_CLASS names it
            "app_id": "editor",
            "monitor": 0,
            "state": ["normal"],
        },
    ]


def test_should_focus_a_window_by_title_words_and_say_it_is_focused() -> None:
    fake = _fake()
    reply = _call(_backend(fake), "focus_window", ref="notes")
    assert reply["ok"] is True
    assert reply["result"]["ref"] == "x11:0x10"
    assert "focused" in reply["result"]["state"]
    assert fake.active == 0x10


def test_should_run_a_window_op_and_report_the_windows_it_touched() -> None:
    fake = _fake()
    reply = _call(_backend(fake), "window_op", ref="x11:0x20", op="maximize")
    assert reply["ok"] is True
    assert reply["result"]["op"] == "maximize"
    assert reply["result"]["windows"][0]["state"] == ["maximized", "focused"]
    assert {"MAXIMIZED_VERT", "MAXIMIZED_HORZ"} <= fake.windows[0x20].states


def test_should_pass_the_monitor_and_the_tile_partners_to_the_op() -> None:
    fake = _fake()
    reply = _call(_backend(fake), "window_op", ref="calc", op="tile", with_refs=["notes"])
    assert reply["ok"] is True
    assert [w["ref"] for w in reply["result"]["windows"]] == ["x11:0x20", "x11:0x10"]


def test_should_answer_not_found_with_the_closest_titles() -> None:
    reply = _call(_backend(_fake()), "focus_window", ref="Calculater")
    assert reply["ok"] is False
    assert reply["error"]["code"] == "NOT_FOUND"
    assert "Calculator" in reply["error"]["alternatives"]


def test_should_answer_invalid_argument_for_an_unknown_op() -> None:
    reply = _call(_backend(_fake()), "window_op", ref="calc", op="explode")
    assert reply["error"]["code"] == "INVALID_ARGUMENT"


def test_should_say_why_when_there_is_no_x11_session() -> None:
    down = X11Error("UNSUPPORTED_ON_PLATFORM", "Jarvis needs an X11 session")
    backend = _backend(port_error=down)
    for op, args in (
        ("list_windows", {}),
        ("focus_window", {"ref": "a"}),
        ("window_op", {"ref": "a", "op": "close"}),
    ):
        reply = _call(backend, op, **args)
        assert reply["error"] == {
            "code": "UNSUPPORTED_ON_PLATFORM",
            "message": "Jarvis needs an X11 session",
        }


@pytest.mark.parametrize(
    "args",
    [{"ref": 5, "op": "close"}, {"ref": "a", "op": "tile", "with_refs": "b"}, {"ref": "a"}],
)
def test_should_refuse_malformed_window_op_arguments(args: dict[str, object]) -> None:
    reply = _call(_backend(_fake()), "window_op", **args)
    assert reply["ok"] is False
    assert reply["error"]["code"] == "INTERNAL"


def test_should_report_apps_and_whether_one_is_running_through_the_worker() -> None:
    backend = _backend(_fake())
    apps = _call(backend, "list_apps")
    assert apps["result"]["apps"][0]["name"] == "Calculator"
    running = _call(backend, "is_running", query="calculator")
    assert running["result"]["running"] is False  # the hook lists no windows here


def test_should_carry_the_alternatives_from_the_worker_to_the_caller() -> None:
    script = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        "    r = json.loads(line)\n"
        "    e = {'code': 'NOT_FOUND', 'message': 'no window', 'alternatives': ['A', 'B']}\n"
        "    print(json.dumps({'id': r['id'], 'ok': False, 'error': e}), flush=True)\n"
    )

    async def scenario() -> DesktopError:
        client = DesktopClient([sys.executable, "-c", script])
        try:
            with pytest.raises(DesktopError) as info:
                await client.focus_window("zzz")
            return info.value
        finally:
            await client.close()

    error = asyncio.run(scenario())
    assert (error.code, error.alternatives) == ("NOT_FOUND", ("A", "B"))
