import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from jarvis.hud import supervisor

WINDOW_PATH = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "hud" / "window.py"


def _load_window_module() -> Any:
    spec = importlib.util.spec_from_file_location("hud_window", WINDOW_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_should_keep_allowed_names_and_prefixes_when_environ_has_them() -> None:
    environ = {
        "DISPLAY": ":1",
        "XAUTHORITY": "/x/auth",
        "HOME": "/h",
        "USER": "u",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "C",
        "XDG_RUNTIME_DIR": "/run/u",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/b",
        "PATH": "/usr/bin",
    }
    result = supervisor.window_env("tok", environ)
    assert result == {**environ, "JARVIS_HUD_TOKEN": "tok"}


def test_should_leave_out_secrets_when_environ_has_them() -> None:
    environ = {
        "ANTHROPIC_API_KEY": "k",
        "GITHUB_TOKEN": "g",
        "PYTHONPATH": "/evil",
        "SECRET": "s",
        "DISPLAY": ":1",
    }
    result = supervisor.window_env("tok", environ)
    assert set(result) == {"DISPLAY", "JARVIS_HUD_TOKEN"}


def test_should_omit_absent_allowed_names_when_only_path_given() -> None:
    result = supervisor.window_env("tok", {"PATH": "/usr/bin"})
    assert set(result) == {"PATH", "JARVIS_HUD_TOKEN"}


def test_should_prefer_new_token_when_inherited_token_present() -> None:
    environ = {"JARVIS_HUD_TOKEN": "old", "PATH": "/usr/bin"}
    result = supervisor.window_env("new", environ)
    assert result["JARVIS_HUD_TOKEN"] == "new"  # noqa: S105


def test_should_default_to_real_environ_when_environ_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOME_SECRET_FOR_TEST", "x")
    monkeypatch.setenv("LC_TIME", "C")
    result = supervisor.window_env("tok")
    assert "SOME_SECRET_FOR_TEST" not in result
    assert "LC_TIME" in result


def test_should_pass_minimal_env_to_exec_when_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_SECRET_FOR_TEST", "x")
    captured: dict[str, Any] = {}

    async def fake_exec(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()

    async def scenario() -> None:
        await supervisor.window_spawner(
            "python3", "http://127.0.0.1:1/hud", "tok", exec_fn=fake_exec
        )()

    asyncio.run(scenario())
    assert captured["env"]["JARVIS_HUD_TOKEN"] == "tok"  # noqa: S105
    assert "SOME_SECRET_FOR_TEST" not in captured["env"]


def test_should_pop_token_from_environ_when_main_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_HUD_TOKEN", "secret")
    monkeypatch.setitem(sys.modules, "gi", None)
    module = _load_window_module()
    rc = module.main(["--url", "http://127.0.0.1:1/hud"])
    assert rc == 78
    assert "JARVIS_HUD_TOKEN" not in os.environ


def test_should_return_2_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_HUD_TOKEN", raising=False)
    monkeypatch.setitem(sys.modules, "gi", None)
    module = _load_window_module()
    rc = module.main(["--url", "http://127.0.0.1:1/hud"])
    assert rc == 2
