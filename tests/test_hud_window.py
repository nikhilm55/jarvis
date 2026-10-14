import ast
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

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


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Jarvis HUD:visible", True),
        ("Jarvis HUD:hidden", False),
        (None, None),
        ("", None),
        ("Jarvis HUD:other", None),
        ("x", None),
    ],
)
def test_should_map_title_to_visibility_when_given_title(
    title: str | None,
    expected: bool | None,
) -> None:
    module = _load_window()
    assert module.visible_from_title(title) is expected


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
