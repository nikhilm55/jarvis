"""ClaudeCodeBrain: a warm headless Claude Code session driven over stream-json."""

import asyncio
import time
from typing import Any

from jarvis.brain.agent_bin import resolve_claude
from jarvis.brain.clock import TurnClock
from jarvis.brain.desktop_tools import DesktopLike
from jarvis.brain.dispatch import OnAsk, OnSay, TurnHooks, TurnTools
from jarvis.brain.events import result_response
from jarvis.brain.failures import (
    BrainUnavailable,
    ToolError,
    process_exit_response,
    timeout_response,
)
from jarvis.brain.launch import McpConfigWriter, prepare_launch
from jarvis.brain.process import ClaudeProcess
from jarvis.config import Settings
from jarvis.contract import FinalResponse, TurnEnvelope
from jarvis.log import get_logger

__all__ = ["ClaudeCodeBrain"]

_Item = dict[str, Any] | FinalResponse | None
_DRAIN_TIMEOUT_S = 10.0


class ClaudeCodeBrain:
    """A warm headless Claude Code session driven over stream-json.

    Construct the MCP server with ``lambda name, args: brain.dispatch(name, args)``
    (late-bound) because the server needs its dispatch before the brain exists.
    """

    def __init__(
        self, settings: Settings, mcp_server: McpConfigWriter, desktop: DesktopLike
    ) -> None:
        """Initialise the brain with settings, an MCP writer and a desktop."""
        self._brain = settings.brain
        self._mcp = mcp_server
        self._desktop = desktop
        self._proc: ClaudeProcess | None = None
        self._queue: asyncio.Queue[_Item] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._tools: TurnTools | None = None
        self._pending_result = False
        self._closed = False
        self._log = get_logger("brain")

    @property
    def pid(self) -> int | None:
        """Return the pid of the running claude process, or None."""
        return self._proc.pid if self._proc is not None else None

    async def start(self) -> None:
        """Ensure the claude process is running."""
        async with self._lock:
            await self._ensure_process()

    async def dispatch(self, policy_name: str, args: dict[str, object]) -> object:
        """Dispatch a tool call to the active turn."""
        tools = self._tools
        if tools is None:
            raise ToolError("no active turn")
        return await tools(policy_name, args)

    async def turn(self, envelope: TurnEnvelope, on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
        """Run one user turn against the brain."""
        async with self._lock:
            try:
                await self._ensure_process()
                await self._drain_tail()
            except BrainUnavailable as exc:
                return exc.to_response()

            proc = self._proc
            if proc is None:
                return process_exit_response()

            clock = TurnClock()
            queue = self._queue
            tools = TurnTools(
                envelope.turn_id,
                TurnHooks(on_say, on_ask, queue.put_nowait, clock),
                self._desktop,
                self._brain.max_steps,
            )
            self._tools = tools
            started = time.monotonic()

            try:
                async with asyncio.timeout(self._brain.turn_timeout_s) as scope:
                    clock.attach(scope)
                    await proc.send(envelope.to_json())
                    response = await self._collect()
            except TimeoutError:
                await self._drop_process("turn timed out")
                response = timeout_response(self._brain.turn_timeout_s)
            except OSError:
                await self._drop_process("claude stdin closed")
                response = process_exit_response()
            except asyncio.CancelledError:
                await self._drop_process("turn cancelled")
                raise
            finally:
                tools.close()
                self._tools = None

            self._log.info(
                "brain turn",
                extra={
                    "turn_id": envelope.turn_id,
                    "ms": int((time.monotonic() - started) * 1000),
                    "steps": tools.steps,
                    "repair_used": tools.repair_used,
                    "status": response.status,
                },
            )
            return response

    async def _collect(self) -> FinalResponse:
        """Collect stream-json events until the turn resolves."""
        assistant_error: str | None = None
        while True:
            item = await self._queue.get()
            if item is None:
                await self._drop_process("claude closed its output")
                return process_exit_response()
            if isinstance(item, FinalResponse):
                self._pending_result = True
                return item
            kind = item.get("type")
            if kind == "assistant":
                err = item.get("error")
                if isinstance(err, str):
                    assistant_error = err
            elif kind == "result":
                return result_response(item, assistant_error, self._log)

    async def _ensure_process(self) -> None:
        """Spawn the claude process if it is not already running."""
        if self._closed:
            raise BrainUnavailable("Jarvis is shutting down", ["Start Jarvis again."])
        if self._proc is not None and self._proc.alive:
            return
        if self._proc is not None:
            await self._drop_process("claude exited")
        binary = resolve_claude(self._brain.claude_bin)
        spec = prepare_launch(binary, self._brain, self._mcp)
        self._queue = asyncio.Queue()
        self._pending_result = False
        self._proc = await ClaudeProcess.spawn(spec, self._queue.put_nowait)
        self._log.info("brain started", extra={"pid": self._proc.pid, "model": self._brain.model})

    async def _drain_tail(self) -> None:
        """Drain the trailing result event from the previous turn."""
        if not self._pending_result:
            return
        try:
            async with asyncio.timeout(_DRAIN_TIMEOUT_S):
                while True:
                    item = await self._queue.get()
                    if item is None:
                        raise ConnectionError("claude closed")
                    if isinstance(item, dict) and item.get("type") == "result":
                        break
        except (TimeoutError, ConnectionError):
            await self._drop_process("previous turn never finished")
            await self._ensure_process()
            return
        self._pending_result = False

    async def _drop_process(self, reason: str) -> None:
        """Kill the claude process and reset internal state."""
        proc = self._proc
        self._proc = None
        self._pending_result = False
        self._queue = asyncio.Queue()
        self._log.info("brain stopped", extra={"reason": reason})
        if proc is not None:
            await proc.kill()

    async def close(self) -> None:
        """Close the brain and kill the claude process."""
        self._closed = True
        proc = self._proc
        self._proc = None
        if proc is not None:
            await proc.kill()
