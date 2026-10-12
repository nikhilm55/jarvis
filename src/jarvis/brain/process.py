"""One claude child process on the stream-json protocol, in its own process group."""

import asyncio
import contextlib
import json
import os
import signal
import sys
from collections.abc import Callable
from typing import Any, Self

from jarvis.brain.failures import BrainUnavailable
from jarvis.brain.launch import LaunchSpec
from jarvis.log import get_logger

__all__ = ["ClaudeProcess", "Sink"]

Sink = Callable[[dict[str, Any] | None], None]

_LINE_LIMIT = 8 * 1024 * 1024
_TERM_GRACE_S = 2.0


class ClaudeProcess:
    """A single claude child process speaking stream-json over stdio."""

    def __init__(self, proc: asyncio.subprocess.Process, sink: Sink) -> None:
        """Store the process and sink, then start the stdout reader task."""
        self._proc = proc
        self._sink = sink
        self._killed = False
        self._log = get_logger("brain")
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def spawn(cls, spec: LaunchSpec, sink: Sink) -> Self:
        """Start the claude process in its own session and wrap it."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=spec.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                limit=_LINE_LIMIT,
            )
        except OSError as exc:
            raise BrainUnavailable(
                f"Claude Code could not be started ({exc.strerror or exc})",
                ["Check that the claude command runs in a terminal, then ask again."],
            ) from exc
        return cls(proc, sink)

    @property
    def pid(self) -> int:
        """Return the operating-system process id of the child."""
        return self._proc.pid

    @property
    def alive(self) -> bool:
        """Return True while the process is running and the reader is active."""
        return self._proc.returncode is None and not self._reader.done() and not self._killed

    async def send(self, text: str) -> None:
        """Write a user message to the child's stdin as a stream-json line."""
        stdin = self._proc.stdin
        if stdin is None:
            raise ConnectionResetError("claude stdin is closed")
        payload = json.dumps(
            {"type": "user", "message": {"role": "user", "content": text}},
            ensure_ascii=False,
        )
        stdin.write((payload + "\n").encode("utf-8"))
        await stdin.drain()

    async def _read(self) -> None:
        """Read stream-json events from stdout until the stream closes."""
        stdout = self._proc.stdout
        if stdout is None:
            self._sink(None)
            return
        try:
            while True:
                try:
                    line = await stdout.readline()
                except ValueError:
                    self._log.warning("claude event too long")
                    break
                if not line:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    self._log.debug("skipping non-JSON line from claude")
                    continue
                if isinstance(event, dict):
                    self._sink(event)
        finally:
            self._sink(None)

    def _signal_group(self, sig: int) -> None:
        """Signal the whole process group, falling back to a direct kill on Windows."""
        if sys.platform == "win32":
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self._proc.pid, sig)

    async def kill(self) -> None:
        """Terminate the process group gracefully, then forcefully, and clean up."""
        if self._killed:
            return
        self._killed = True
        stdin = self._proc.stdin
        if stdin is not None:
            with contextlib.suppress(OSError):
                stdin.close()
        self._signal_group(signal.SIGTERM)
        try:
            await asyncio.wait_for(self._proc.wait(), _TERM_GRACE_S)
        except TimeoutError:
            self._signal_group(signal.SIGKILL)
            await self._proc.wait()
        self._signal_group(signal.SIGKILL)  # stray grandchildren outlive their leader
        await asyncio.gather(self._reader, return_exceptions=True)
