"""ClaudeCodeBrain end to end: the real MCP server and a fake claude, the happy paths."""

import asyncio
import sys
from pathlib import Path

import pytest

from jarvis.brain.failures import ToolError
from tests.brain_fakes import FakeClaude, envelope
from tests.brain_rig import finish, play, respond, running_brain


def test_should_return_the_response_when_respond_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok: dict[str, object] = {"status": "success", "spoken": "Calculator is open."}
    responses, _, fake = play(tmp_path, monkeypatch, [finish(respond(ok))])
    assert (responses[0].status, responses[0].spoken) == ("success", "Calculator is open.")
    assert {"user": envelope("open calculator").to_json()} in fake.records()


def test_should_reuse_one_warm_process_when_two_turns_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns = [finish(respond()), finish(respond())]
    responses, _, fake = play(tmp_path, monkeypatch, turns, count=2)
    assert [r.status for r in responses] == ["success", "success"]
    assert len(fake.spawns()) == 1


def test_should_route_say_and_ask_when_the_turn_uses_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ask = {"question": "Which colour?", "options": ["red", "blue"]}
    say = {"call": "say", "args": {"text": "Working on it."}}
    _, rig, fake = play(
        tmp_path, monkeypatch, [finish(say, {"call": "ask", "args": ask}, respond())]
    )
    assert rig.cb.said == ["Working on it."]
    assert rig.cb.asked == [("Which colour?", ["red", "blue"])]
    assert [c["text"] for c in fake.tool_calls() if c["tool"] == "ask"] == ["blue"]


def test_should_route_desktop_calls_when_the_brain_opens_an_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_app = {"call": "open_app", "args": {"name": "Calculator"}}
    _, rig, fake = play(tmp_path, monkeypatch, [finish(open_app, respond())])
    assert rig.desktop.calls == [("open_app", "Calculator")]
    assert "Calculator" in fake.tool_calls()[0]["text"]


def test_should_reject_dispatch_when_no_turn_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClaude(tmp_path, monkeypatch, [])

    async def main() -> None:
        async with running_brain(fake) as rig:
            with pytest.raises(ToolError, match="no active turn"):
                await rig.brain.dispatch("jarvis.say", {"text": "hi"})

    asyncio.run(main())


def test_should_launch_claude_isolated_when_a_turn_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, fake = play(tmp_path, monkeypatch, [finish(respond())])
    argv = fake.spawns()[0]
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == "mcp__jarvis__*"
    assert all(".claude" not in arg for arg in argv)


def test_should_start_claude_with_an_allowlisted_environment_when_a_turn_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDECODE"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("MCP_TIMEOUT", "1")
    _, _, fake = play(tmp_path, monkeypatch, [finish(respond())])
    names = set(fake.records()[0]["env"])
    assert not [n for n in names if n.startswith(("ANTHROPIC_", "CLAUDE", "MCP_", "OTEL_"))]
    home = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert {"PATH", home, "JARVIS_MCP_TOKEN", "FAKE_CLAUDE_SCENARIO"} <= names
