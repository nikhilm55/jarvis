import ast
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from jarvis.hud.server import HudServer
from jarvis.orchestrator.hud import HudEvent
from tests.hud_rig import until

WINDOW_PATH = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "hud" / "window.py"


def _load_window() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("hud_window", WINDOW_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_should_allow_import_without_gi_when_gi_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gi", None)
    module = _load_window()
    assert module is not None


def test_should_only_import_stdlib_and_gi_when_parsing_source() -> None:
    tree = ast.parse(WINDOW_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    allowed = sys.stdlib_module_names | {"gi"}
    assert names <= allowed
    assert "jarvis" not in names
    assert "gi" in names


def test_should_return_url_when_parsing_args_with_url() -> None:
    module = _load_window()
    ns = module.parse_args(["--url", "http://x/hud"])
    assert ns.url == "http://x/hud"


def test_should_exit_when_parsing_args_without_url() -> None:
    module = _load_window()
    with pytest.raises(SystemExit):
        module.parse_args([])


def test_should_centre_window_on_bottom_edge_when_given_main_area() -> None:
    module = _load_window()
    assert module.placement((0, 32, 1920, 1097), 612, 140) == (654, 989)


def test_should_centre_window_on_bottom_edge_when_given_secondary_area() -> None:
    module = _load_window()
    assert module.placement((1920, 0, 1280, 1024), 612, 140) == (2254, 884)


def test_should_append_plain_token_when_page_url_has_safe_chars() -> None:
    module = _load_window()
    assert module.page_url("http://127.0.0.1:5/hud", "ab-_c") == "http://127.0.0.1:5/hud#ab-_c"


def test_should_escape_token_when_page_url_has_special_chars() -> None:
    module = _load_window()
    assert module.page_url("http://127.0.0.1:5/hud", "a b/c") == "http://127.0.0.1:5/hud#a%20b%2Fc"


def test_should_return_usage_when_main_has_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_HUD_TOKEN", raising=False)
    module = _load_window()
    assert module.main(["--url", "http://127.0.0.1:5/hud"]) == module.EXIT_USAGE


def test_should_return_usage_when_main_has_empty_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_HUD_TOKEN", "")
    module = _load_window()
    assert module.main(["--url", "http://127.0.0.1:5/hud"]) == module.EXIT_USAGE


def test_should_return_no_gui_when_main_cannot_import_gi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_HUD_TOKEN", "secret")
    monkeypatch.setitem(sys.modules, "gi", None)
    module = _load_window()
    assert module.main(["--url", "http://127.0.0.1:5/hud"]) == module.EXIT_NO_GUI


@pytest.mark.desktop
@pytest.mark.skipif(
    not os.environ.get("DISPLAY") or os.environ.get("JARVIS_LIVE_DESKTOP") != "1",
    reason="live desktop test: set DISPLAY and JARVIS_LIVE_DESKTOP=1",
)
def test_should_stream_events_when_live_desktop_is_available() -> None:
    module = _load_window()

    async def scenario() -> None:
        server = HudServer()
        await server.start()
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/python3",
            "-I",
            str(WINDOW_PATH),
            "--url",
            server.url,
            env={**os.environ, module.TOKEN_ENV: server.token},
        )
        try:
            await until(lambda: server.client_count == 1)  # the fragment token authenticated
            await asyncio.to_thread(_assert_click_through)
            await server.publish(HudEvent("listening", "Listening..."))
            await server.publish(HudEvent("speaking", "Teams is open."))
            process.terminate()
            assert await asyncio.wait_for(process.wait(), 5) == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await server.close()

    asyncio.run(scenario())


def _assert_click_through() -> None:
    """The HUD's X window has an empty input shape: every click falls through it."""
    from Xlib import display  # noqa: PLC0415 - only the live test needs an X connection
    from Xlib.ext import shape  # noqa: PLC0415

    def find(window: Any) -> Any:
        if (window.get_wm_name() or "") == "Jarvis HUD":
            return window
        for child in window.query_tree().children:
            found = find(child)
            if found is not None:
                return found
        return None

    conn = display.Display()
    try:
        hud = find(conn.screen().root)
        assert hud is not None
        assert hud.shape_get_rectangles(shape.SK.Input).rectangles == []
    finally:
        conn.close()
