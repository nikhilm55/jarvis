"""Asyncio client for the desktop worker process.

DesktopClient does NOT call the policy gate itself - callers (the fast path
and the MCP handlers) must reach it through ``jarvis.policy.gated_dispatch``.
"""

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Sequence


class DesktopError(Exception):
    """Raised when the desktop worker reports an error or the client is unusable."""

    def __init__(self, code: str, message: str, alternatives: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.alternatives = tuple(alternatives)

    def __str__(self) -> str:
        return self.message


class _WorkerGone(Exception):
    """Internal: the worker process is gone or produced an unusable response."""


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Kill and wait for a process, suppressing expected errors."""
    with contextlib.suppress(ProcessLookupError, OSError):
        proc.kill()
    with contextlib.suppress(ProcessLookupError, OSError):
        await proc.wait()


class DesktopClient:
    """Talks to the desktop worker process (JSON lines on stdin/stdout).

    DesktopClient does NOT call the policy gate itself - callers (the fast path
    and the MCP handlers) must reach it through ``jarvis.policy.gated_dispatch``.
    """

    def __init__(
        self,
        command: Sequence[str] | None = None,
        timeout_s: float = 5.0,
        open_timeout_s: float = 10.0,
        window_op_timeout_s: float = 10.0,
    ) -> None:
        self._command = (
            list(command)
            if command is not None
            else [
                sys.executable,
                "-m",
                "jarvis.desktop.worker",
            ]
        )
        self._timeout_s = timeout_s
        self._open_timeout_s = open_timeout_s
        self._window_op_timeout_s = window_op_timeout_s
        self._input_timeout_s = max(timeout_s, 20.0)  # typing 200 characters key by key
        self._proc: asyncio.subprocess.Process | None = None
        self._stdin: asyncio.StreamWriter | None = None
        self._stdout: asyncio.StreamReader | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._closed = False

    async def open_app(self, query: str) -> dict[str, object]:
        """Open an application by query (not idempotent)."""
        return await self._call("open_app", {"query": query}, self._open_timeout_s, False)

    async def close_app(self, query: str) -> dict[str, object]:
        """Close an application by query (idempotent)."""
        return await self._call("close_app", {"query": query}, self._timeout_s, True)

    async def list_windows(self) -> dict[str, object]:
        """List the user's windows, frontmost first (idempotent)."""
        return await self._call("list_windows", {}, self._timeout_s, True)

    async def focus_window(self, ref: str) -> dict[str, object]:
        """Bring a window to the front and focus it (idempotent)."""
        return await self._call("focus_window", {"ref": ref}, self._timeout_s, True)

    async def window_op(
        self,
        ref: str,
        op: str,
        monitor: int | None = None,
        with_refs: Sequence[str] = (),
    ) -> dict[str, object]:
        """Minimise, maximise, restore, close, snap, move or tile windows (not idempotent)."""
        args: dict[str, object] = {"ref": ref, "op": op}
        if monitor is not None:
            args["monitor"] = monitor
        if with_refs:
            args["with_refs"] = list(with_refs)
        return await self._call("window_op", args, self._window_op_timeout_s, False)

    async def list_apps(self) -> dict[str, object]:
        """List the installed apps (idempotent)."""
        return await self._call("list_apps", {}, self._timeout_s, True)

    async def is_running(self, query: str) -> dict[str, object]:
        """Whether an app has a window open (idempotent)."""
        return await self._call("is_running", {"query": query}, self._timeout_s, True)

    async def type_text(self, text: str) -> dict[str, object]:
        """Type text into the focused field (not idempotent: never retried)."""
        return await self._call("type_text", {"text": text}, self._input_timeout_s, False)

    async def press_keys(self, combo: str) -> dict[str, object]:
        """Press a key combination (not idempotent)."""
        return await self._call("press_keys", {"combo": combo}, self._timeout_s, False)

    async def click(
        self, x: int, y: int, button: str = "left", count: int = 1
    ) -> dict[str, object]:
        """Click at screen coordinates (not idempotent)."""
        args: dict[str, object] = {"x": x, "y": y, "button": button, "count": count}
        return await self._call("click", args, self._timeout_s, False)

    async def scroll(self, dx: int, dy: int) -> dict[str, object]:
        """Scroll by notches (not idempotent)."""
        return await self._call("scroll", {"dx": dx, "dy": dy}, self._timeout_s, False)

    async def volume_get(self) -> dict[str, object]:
        """Get the current volume (idempotent)."""
        return await self._call("volume_get", {}, self._timeout_s, True)

    async def volume_set(self, pct: int) -> dict[str, object]:
        """Set the volume percentage (idempotent)."""
        return await self._call("volume_set", {"pct": pct}, self._timeout_s, True)

    async def volume_step(self, delta: int) -> dict[str, object]:
        """Step the volume by a delta (not idempotent)."""
        return await self._call("volume_step", {"delta": delta}, self._timeout_s, False)

    async def mute(self, on: bool) -> dict[str, object]:
        """Mute or unmute (idempotent)."""
        return await self._call("mute", {"on": on}, self._timeout_s, True)

    async def close(self) -> None:
        """Close the client and terminate the worker process (idempotent)."""
        self._closed = True
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        stdin = self._stdin
        self._stdin = None
        self._stdout = None
        if stdin is not None:
            stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (TimeoutError, ProcessLookupError, OSError, BrokenPipeError):
            with contextlib.suppress(ProcessLookupError, OSError):
                proc.kill()
            with contextlib.suppress(ProcessLookupError, OSError):
                await proc.wait()

    async def _call(
        self,
        op: str,
        args: dict[str, object],
        timeout: float,
        idempotent: bool,
    ) -> dict[str, object]:
        if self._closed:
            raise DesktopError("INTERNAL", "desktop client is closed")
        attempts = 2 if idempotent else 1
        async with self._lock:
            if self._closed:
                raise DesktopError("INTERNAL", "desktop client is closed")
            for attempt in range(attempts):
                try:
                    return await self._roundtrip(op, args, timeout)
                except _WorkerGone:
                    await self._kill()
                    if attempt < attempts - 1:
                        continue
                    raise DesktopError(
                        "INTERNAL",
                        "desktop worker crashed"
                        if idempotent
                        else "desktop worker crashed during a call that cannot be "
                        "safely repeated - check the result and try again",
                    ) from None
        raise DesktopError("INTERNAL", "no attempt was made")

    async def _roundtrip(
        self,
        op: str,
        args: dict[str, object],
        timeout: float,
    ) -> dict[str, object]:
        try:
            async with asyncio.timeout(timeout):
                return await self._do_roundtrip(op, args)
        except TimeoutError:
            await self._kill()
            raise DesktopError(
                "TIMEOUT",
                f"desktop worker did not answer {op} within {timeout:g} s",
            ) from None

    async def _do_roundtrip(self, op: str, args: dict[str, object]) -> dict[str, object]:
        writer, reader = await self._spawn()
        req_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"id": req_id, "op": op, "args": args}) + "\n"
        try:
            writer.write(payload.encode("utf-8"))
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            raise _WorkerGone() from None
        while True:
            try:
                line = await reader.readline()
            except ValueError:
                raise _WorkerGone() from None
            if not line:
                raise _WorkerGone()
            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _WorkerGone() from None
            if not isinstance(response, dict) or response.get("id") != req_id:
                continue
            if response.get("ok"):
                result = response.get("result")
                if isinstance(result, dict):
                    return result
                raise _WorkerGone()
            error = response.get("error", {})
            code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
            message = error.get("message", "") if isinstance(error, dict) else ""
            raw = error.get("alternatives") if isinstance(error, dict) else None
            names = [str(a) for a in raw] if isinstance(raw, list) else []
            raise DesktopError(str(code), str(message), names)

    async def _spawn(self) -> tuple[asyncio.StreamWriter, asyncio.StreamReader]:
        if self._closed:
            raise DesktopError("INTERNAL", "desktop client is closed")
        if (
            self._proc is not None
            and self._proc.returncode is None
            and self._stdin is not None
            and self._stdout is not None
        ):
            return self._stdin, self._stdout
        if self._proc is not None:
            await self._kill()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # Own session: a Ctrl-C aimed at Jarvis must not reach the worker before
                # Jarvis closes it (R30). Windows has no sessions to start.
                start_new_session=os.name == "posix",
            )
        except OSError:
            raise DesktopError("INTERNAL", "could not start the desktop worker") from None
        if self._closed:
            await _reap(proc)
            raise DesktopError("INTERNAL", "desktop client is closed")
        if proc.stdin is None or proc.stdout is None:
            await _reap(proc)
            raise DesktopError("INTERNAL", "could not start the desktop worker")
        self._proc = proc
        self._stdin = proc.stdin
        self._stdout = proc.stdout
        return proc.stdin, proc.stdout

    async def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        self._stdin = None
        self._stdout = None
        if proc is None:
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
        with contextlib.suppress(ProcessLookupError, OSError):
            await proc.wait()
