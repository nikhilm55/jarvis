"""Fake `claude` CLI for brain tests: replays a JSON scenario over the stream-json protocol."""

import asyncio
import contextlib
import json
import os
import subprocess
import sys
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import TextContent


def _read_json(path: str) -> Any:
    """Load a JSON file from disk."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _read_state(path: str) -> int:
    """Return the stored user-message count, defaulting to zero."""
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 0


def _write_state(path: str, value: int) -> None:
    """Persist the user-message count to disk."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(value))


def _log(path: str, payload: dict[str, Any]) -> None:
    """Append one JSON line to the log file."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def _spawn_child(pidfile: str) -> None:
    """Spawn a long-lived child and record its pid."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    with open(pidfile, "w", encoding="utf-8") as fh:
        fh.write(str(proc.pid))


def _emit(event: dict[str, Any]) -> None:
    """Write one JSON event to stdout, flushing immediately."""
    print(json.dumps(event), flush=True)


def _init_event(status: str) -> dict[str, Any]:
    """Build the system init event for a given MCP status."""
    return {
        "type": "system",
        "subtype": "init",
        "session_id": "fake",
        "mcp_servers": [{"name": "jarvis", "status": status}],
    }


def _tool_use_event(index: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build the assistant tool_use event for a tool call."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"tu{index}",
                    "name": f"mcp__jarvis__{name}",
                    "input": args,
                }
            ],
        },
    }


def _tool_result_event(index: int, text: str) -> dict[str, Any]:
    """Build the user tool_result event for a tool call."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": f"tu{index}",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        },
    }


def _text_event(text: str) -> dict[str, Any]:
    """Build an assistant text event."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _error_event(code: str, text: str) -> dict[str, Any]:
    """Build an assistant text event carrying an error code."""
    event = _text_event(text)
    event["error"] = code
    return event


def _result_event(text: str, is_error: bool) -> dict[str, Any]:
    """Build the terminal result event for a turn."""
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": text,
        "session_id": "fake",
    }


def _find_mcp_config(argv: list[str]) -> str | None:
    """Locate the --mcp-config argument value in argv, if present."""
    for i, arg in enumerate(argv):
        if arg == "--mcp-config" and i + 1 < len(argv):
            return argv[i + 1]
    return None


class _Mcp:
    """The MCP client, opened on the first tool call and kept for the life of the process."""

    def __init__(self, config_path: str | None) -> None:
        self._config_path = config_path
        self._stack = contextlib.AsyncExitStack()
        self._client: Client | None = None

    async def close(self) -> None:
        """Close the client and its HTTP session."""
        await self._stack.aclose()

    async def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Call a tool and return (result text, is_error)."""
        if self._client is None:
            if self._config_path is None:
                raise RuntimeError("no --mcp-config in argv")
            server = _read_json(self._config_path)["mcpServers"]["jarvis"]
            headers = {k: os.path.expandvars(v) for k, v in server.get("headers", {}).items()}
            http = httpx2.AsyncClient(headers=headers)
            await self._stack.enter_async_context(http)
            client = Client(streamable_http_client(server["url"], http_client=http), mode="auto")
            self._client = await self._stack.enter_async_context(client)
        result = await self._client.call_tool(name, args)
        block = result.content[0]
        return (block.text if isinstance(block, TextContent) else ""), bool(result.is_error)


async def _call(mcp: _Mcp, index: int, action: dict[str, Any], log_path: str | None) -> None:
    """Play one `call` action: tool_use event, the MCP call, tool_result event."""
    name, args = action["call"], action.get("args", {})
    _emit(_tool_use_event(index, name, args))
    text, is_error = await mcp.call(name, args)
    _emit(_tool_result_event(index, text))
    if log_path:
        _log(log_path, {"tool": name, "text": text, "is_error": is_error})


async def _play_turn(turn: list[dict[str, Any]], mcp: _Mcp, log_path: str | None) -> None:
    """Replay one turn's actions in order."""
    actions = list(turn)
    status = "connected"
    if actions and "init" in actions[0]:
        status = actions.pop(0)["init"]
    _emit(_init_event(status))
    calls = 0
    for action in actions:
        if "call" in action:
            await _call(mcp, calls, action, log_path)
            calls += 1
        elif "text" in action and "error" not in action:
            _emit(_text_event(action["text"]))
        elif "error" in action:
            _emit(_error_event(action["error"], action.get("text", "")))
        elif "result" in action:
            _emit(_result_event(action["result"], action.get("is_error", False)))
        elif "sleep" in action:
            await asyncio.sleep(action["sleep"])
        elif action.get("hang"):
            while True:
                await asyncio.sleep(1)
        elif "exit" in action:
            os._exit(action["exit"])
        elif "noise" in action:
            print(action["noise"], flush=True)
    if log_path:
        _log(log_path, {"turn_done": True})


def _next_turn(
    scenario: list[list[dict[str, Any]]], state_path: str | None
) -> list[dict[str, Any]]:
    """Return the turn for this user message and advance the persisted counter."""
    count = _read_state(state_path) if state_path else 0
    if state_path:
        _write_state(state_path, count + 1)
    return scenario[count] if count < len(scenario) else []


async def _run(argv: list[str]) -> None:
    """Read user messages from stdin and replay one scenario turn for each."""
    log_path = os.environ.get("FAKE_CLAUDE_LOG")
    if log_path:
        _log(log_path, {"argv": argv, "env": sorted(os.environ)})
    if pidfile := os.environ.get("FAKE_CLAUDE_CHILD_PIDFILE"):
        _spawn_child(pidfile)
    scenario = _read_json(os.environ["FAKE_CLAUDE_SCENARIO"])
    state_path = os.environ.get("FAKE_CLAUDE_STATE")
    mcp = _Mcp(_find_mcp_config(argv))
    loop = asyncio.get_running_loop()
    while line := await loop.run_in_executor(None, sys.stdin.readline):
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict) or message.get("type") != "user":
            continue
        if log_path:
            _log(log_path, {"user": message.get("message", {}).get("content", "")})
        await _play_turn(_next_turn(scenario, state_path), mcp, log_path)
    await mcp.close()


def main() -> None:
    """Entry point: run the fake CLI loop."""
    sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows defaults to ANSI
    asyncio.run(_run(sys.argv[1:]))


if __name__ == "__main__":
    main()
