"""Test helpers for the brain: a fake claude executable on disk and process helpers."""

import asyncio
import ctypes
import json
import os
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from jarvis.contract import TurnEnvelope

FAKE_CLAUDE = Path(__file__).parent / "fixtures" / "fake_claude.py"
ENVELOPE_JSON = Path(__file__).parent / "fixtures" / "contract" / "envelope.json"


def envelope(command: str = "open calculator", turn_id: str = "t1") -> TurnEnvelope:
    """Build a TurnEnvelope from the fixture JSON with overrides."""
    data = json.loads(ENVELOPE_JSON.read_text(encoding="utf-8"))
    data.update({"command": command, "turn_id": turn_id})
    return TurnEnvelope.model_validate(data)


class FakeClaude:
    """A fake claude binary wrapper with scenario replay and logging."""

    def __init__(
        self,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
        turns: list[list[dict[str, Any]]],
        *,
        child: bool = False,
    ) -> None:
        """Initialise the fake claude wrapper and environment."""
        scenario = root / "scenario.json"
        scenario.write_text(json.dumps(turns), encoding="utf-8")
        state = root / "state.txt"
        log = root / "log.jsonl"
        monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(scenario))
        monkeypatch.setenv("FAKE_CLAUDE_STATE", str(state))
        monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
        if child:
            monkeypatch.setenv("FAKE_CLAUDE_CHILD_PIDFILE", str(root / "child.pid"))
        wrapper = root / "claude"
        wrapper.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(FAKE_CLAUDE))} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        self.bin = str(wrapper)
        self._log = log
        self._pidfile = root / "child.pid"

    def records(self) -> list[dict[str, Any]]:
        """Return the parsed JSONL log records, or an empty list."""
        if not self._log.exists():
            return []
        lines = self._log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line]

    def spawns(self) -> list[list[str]]:
        """Return the argv lists recorded for each process start."""
        return [rec["argv"] for rec in self.records() if "argv" in rec]

    def tool_calls(self) -> list[dict[str, Any]]:
        """Return the records that represent tool calls."""
        return [rec for rec in self.records() if "tool" in rec]

    def child_pid(self) -> int | None:
        """Return the child pid from the pidfile, or None if missing/unparseable."""
        try:
            return int(self._pidfile.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None


def _windows_process_gone(pid: int) -> bool:
    """Windows liveness probe: os.kill(pid, 0) would send Ctrl+C there, so ask the OS instead."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return True
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
            return True
        return code.value != 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def process_gone(pid: int) -> bool:
    """True when `pid` no longer exists (a zombie that is waiting to be reaped counts as gone)."""
    if sys.platform == "win32":
        return _windows_process_gone(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True
    return stat.rsplit(")", 1)[1].split()[0] == "Z"


async def wait_until(predicate: Callable[[], bool], timeout_s: float = 10.0) -> None:
    """Poll `predicate` until it holds; the timeout only guards against a hung test."""
    async with asyncio.timeout(timeout_s):
        while not predicate():
            await asyncio.sleep(0.02)
