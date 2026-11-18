"""The sealed web researcher: its command line, its environment, its answer and its kill paths.

A fake `claude` (a small Python script) stands in for Claude Code: it records how it was
started and prints a canned result, so nothing here touches the network.
"""

import asyncio
import json
import os
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from jarvis.brain.failures import BrainUnavailable
from jarvis.killswitch import KillSwitch
from jarvis.web.errors import ResearchError
from jarvis.web.researcher import MAX_ANSWER, RESEARCH_RULES, WebResearcher

FAKE = textwrap.dedent(
    """
    import json, os, sys, time
    record, mode = sys.argv[1], sys.argv[2]
    argv = sys.argv[3:]
    def arg(flag):
        return argv[argv.index(flag) + 1]
    with open(record, "w", encoding="utf-8") as fh:
        json.dump({
            "argv": argv,
            "stdin": sys.stdin.read(),
            "env": sorted(os.environ),
            "cwd": os.getcwd(),
            "mcp": json.load(open(arg("--mcp-config"), encoding="utf-8")),
            "settings": json.load(open(arg("--settings"), encoding="utf-8")),
        }, fh)
    if mode == "sleep":
        time.sleep(30)
    if mode == "garbage":
        print("not json")
        print("boom: no network", file=sys.stderr)
        sys.exit(1)
    result = {"ok": "Gold is 13,150 a gram.\\nSources:\\nhttps://example.com/gold",
              "long": "x" * 9000, "error": "API Error: overloaded", "empty": ""}[mode]
    print(json.dumps({"type": "result", "subtype": "success",
                      "is_error": mode == "error", "result": result}))
    """
)


def researcher(tmp_path: Path, mode: str, **kw: object) -> tuple[WebResearcher, Path]:
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    record = tmp_path / "record.json"
    environ = {
        **os.environ,
        "JARVIS_MCP_TOKEN": "decoy-token",  # pragma: allowlist secret
        "MY_BANK_PASSWORD": "decoy-password",  # pragma: allowlist secret
    }
    web = WebResearcher(
        lambda: [sys.executable, str(script), str(record), mode],
        "sonnet",
        root=tmp_path / "web",
        environ=environ,
        **kw,  # type: ignore[arg-type]
    )
    return web, record


def test_should_return_the_answer_and_pass_the_request_on_stdin(tmp_path: Path) -> None:
    web, record = researcher(tmp_path, "ok")
    out = web.research("price of gold per gram in India today")
    assert out == {
        "answer": "Gold is 13,150 a gram.\nSources:\nhttps://example.com/gold",
        "truncated": False,
    }
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["stdin"] == "price of gold per gram in India today"
    assert "price of gold" not in " ".join(seen["argv"])  # the request is not on the command line


def test_should_seal_the_session_to_the_web_tools_only(tmp_path: Path) -> None:
    web, record = researcher(tmp_path, "ok")
    web.research("weather in Delhi")
    seen = json.loads(record.read_text(encoding="utf-8"))
    argv = seen["argv"]

    def arg(flag: str) -> str:
        return str(argv[argv.index(flag) + 1])

    assert arg("--tools") == "WebSearch,WebFetch"
    assert arg("--allowedTools") == "WebSearch,WebFetch"
    assert arg("--permission-mode") == "dontAsk"
    assert arg("--setting-sources") == ""
    assert arg("--model") == "sonnet"
    assert arg("--system-prompt") == RESEARCH_RULES
    assert "--strict-mcp-config" in argv
    assert "--no-session-persistence" in argv
    assert seen["mcp"] == {"mcpServers": {}}  # no Jarvis server: it cannot act on the PC
    denied = seen["settings"]["permissions"]["deny"]
    assert {"Bash", "Write", "Edit", "Read"} <= set(denied)
    assert seen["settings"]["disableAllHooks"] is True
    assert os.path.samefile(seen["cwd"], tmp_path / "web" / "cwd")  # Windows short names


def test_should_not_hand_the_mcp_token_or_other_secrets_to_the_session(tmp_path: Path) -> None:
    web, record = researcher(tmp_path, "ok")
    web.research("news today")
    env = json.loads(record.read_text(encoding="utf-8"))["env"]
    assert "JARVIS_MCP_TOKEN" not in env
    assert "MY_BANK_PASSWORD" not in env
    assert "HOME" in env or "USERPROFILE" in env


def test_should_cap_a_long_answer(tmp_path: Path) -> None:
    web, _ = researcher(tmp_path, "long")
    out = web.research("everything about everything")
    assert out["truncated"] is True
    assert isinstance(out["answer"], str) and len(out["answer"]) == MAX_ANSWER


@pytest.mark.parametrize(("mode", "code"), [("error", "NETWORK"), ("garbage", "NETWORK")])
def test_should_raise_a_coded_error_when_the_search_fails(
    tmp_path: Path, mode: str, code: str
) -> None:
    web, _ = researcher(tmp_path, mode)
    with pytest.raises(ResearchError) as caught:
        web.research("anything")
    assert caught.value.code == code


def test_should_explain_an_empty_answer_as_a_failure(tmp_path: Path) -> None:
    web, _ = researcher(tmp_path, "empty")
    with pytest.raises(ResearchError, match="NETWORK"):
        web.research("anything")


def test_should_report_a_missing_claude_as_unavailable(tmp_path: Path) -> None:
    def missing() -> list[str]:
        raise BrainUnavailable("claude is not installed", ["Install Claude Code"])

    web = WebResearcher(missing, "sonnet", root=tmp_path / "web")
    with pytest.raises(ResearchError) as caught:
        web.research("anything")
    assert caught.value.code == "MCP_UNAVAILABLE"


posix_only = pytest.mark.skipif(
    sys.platform != "linux", reason="the kill paths are POSIX process groups"
)


@posix_only
def test_should_time_out_and_kill_the_session(tmp_path: Path) -> None:
    web, _ = researcher(tmp_path, "sleep", timeout_s=1)
    started = time.monotonic()
    with pytest.raises(ResearchError) as caught:
        web.research("slow question")
    assert caught.value.code == "TIMEOUT"
    assert time.monotonic() - started < 5


@posix_only
def test_should_stop_the_session_when_the_kill_switch_fires(tmp_path: Path) -> None:
    async def stop() -> None:
        return None

    killswitch = KillSwitch(stop)
    web, _ = researcher(tmp_path, "sleep", timeout_s=60)
    web.bind(killswitch.register_process)
    caught: dict[str, BaseException] = {}

    def work() -> None:
        try:
            web.research("slow question")
        except ResearchError as exc:
            caught["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()
    time.sleep(0.5)
    started = time.monotonic()
    threading.Thread(target=lambda: asyncio.run(killswitch.trigger("hotkey"))).start()
    thread.join(timeout=3)
    assert not thread.is_alive(), "the search returned after the kill switch fired"
    assert time.monotonic() - started < 3
    error = caught["error"]
    assert isinstance(error, ResearchError)
    assert error.code == "CANCELLED"
