"""Tests for jarvis.mcp.config_file and JarvisMcpServer.write_client_config."""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from jarvis.mcp.config_file import write_private_json
from jarvis.mcp.server import JarvisMcpServer


def test_should_round_trip_content_when_writing_json(tmp_path: Path) -> None:
    data: dict[str, object] = {"k": [1, "é"]}
    target = tmp_path / "a.json"
    write_private_json(target, data)
    text = target.read_text(encoding="utf-8")
    assert json.loads(text) == data
    assert text.endswith("\n")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_should_set_file_mode_600_when_writing(tmp_path: Path) -> None:
    target = tmp_path / "a.json"
    write_private_json(target, {"k": 1})
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_should_replace_existing_target_when_writing(tmp_path: Path) -> None:
    target = tmp_path / "a.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)
    write_private_json(target, {"k": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_should_leave_no_temp_file_when_writing(tmp_path: Path) -> None:
    write_private_json(tmp_path / "a.json", {"k": 1})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]


def test_should_create_missing_parent_dirs_when_writing(tmp_path: Path) -> None:
    target = tmp_path / "x" / "y" / "c.json"
    write_private_json(target, {"k": 1})
    assert target.exists()


def test_should_raise_and_leave_no_leftover_when_data_not_serialisable(tmp_path: Path) -> None:
    target = tmp_path / "a.json"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(TypeError):
        write_private_json(target, {"bad": object()})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"]
    assert target.read_text(encoding="utf-8") == "old"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_should_create_temp_file_600_at_replacement_when_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[int] = []
    real_replace = os.replace

    def fake_replace(src: str | Path, dst: str | Path) -> None:
        recorded.append(stat.S_IMODE(os.stat(src).st_mode))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fake_replace)
    write_private_json(tmp_path / "a.json", {"k": 1})
    assert recorded[0] == 0o600


def test_should_write_client_config_when_server_started(tmp_path: Path) -> None:
    async def dispatch(tool: str, args: dict[str, object]) -> object:
        return "x"

    async def scenario() -> None:
        server = JarvisMcpServer(dispatch, lambda: "balanced")
        with pytest.raises(RuntimeError):
            server.write_client_config(tmp_path / "c.json")
        assert not (tmp_path / "c.json").exists()
        try:
            await server.start()
            server.write_client_config(tmp_path / "c.json")
        finally:
            await server.close()
        data = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
        assert data == {
            "mcpServers": {
                "jarvis": {
                    "type": "http",
                    "url": server.url,
                    "headers": {"Authorization": f"Bearer {server.token}"},
                }
            }
        }

    asyncio.run(scenario())


def test_should_reference_the_token_by_env_name_when_token_env_is_given(tmp_path: Path) -> None:
    async def dispatch(tool: str, args: dict[str, object]) -> object:
        return "x"

    async def scenario() -> None:
        server = JarvisMcpServer(dispatch, lambda: "balanced")
        await server.start()
        try:
            server.write_client_config(tmp_path / "c.json", token_env="JARVIS_MCP_TOKEN")  # noqa: S106
            text = (tmp_path / "c.json").read_text(encoding="utf-8")
            assert server.token not in text
            headers = json.loads(text)["mcpServers"]["jarvis"]["headers"]
            assert headers == {"Authorization": "Bearer ${JARVIS_MCP_TOKEN}"}
            if sys.platform != "win32":  # Windows has no POSIX mode bits
                assert stat.S_IMODE((tmp_path / "c.json").stat().st_mode) == 0o600
        finally:
            await server.close()

    asyncio.run(scenario())
