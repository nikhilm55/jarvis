"""Run one shell command on the user's PC in its own process group (R84, task 8).

The runner is the only product code that spawns a shell. It never uses `shell=True`
(the argv list form keeps the spawn explicit) and it caps and separates the output
streams, so no command can flood Jarvis.

Kill paths (R84): the runner's own timeout kills the process group, and the turn's
kill switch (`KillSwitch.register_process`) kills it the same way, within 300 ms of
`Jarvis, stop` or `Ctrl+Alt+Esc`.
"""

import contextlib
import os
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_TIMEOUT_S", "MAX_CAPTURE", "ShellRunner"]

DEFAULT_TIMEOUT_S = 60.0
MAX_CAPTURE = 64 * 1024  # characters kept from each stream

_Register = Callable[[int], Callable[[], None]]

_Windows = os.name == "nt"

_WINDOWS_CTRL_C_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _no_register(_pid: int) -> Callable[[], None]:
    """Stand-in for the kill switch when no runner is bound (tests, fast paths)."""
    return lambda: None


def _kill_group(pgid: int) -> None:
    """Kill a POSIX process group with SIGKILL (best effort: a dead group stays dead)."""
    with contextlib.suppress(OSError):
        os.killpg(pgid, signal.SIGKILL)


class ShellRunner:
    """One command, one process group, capped streams, a hard timeout (R84)."""

    def __init__(self, *, register: _Register | None = None) -> None:
        """Take `KillSwitch.register_process` (or a fake) so a stop kills running shells."""
        self._register: _Register = register or _no_register

    def bind(self, register: _Register) -> None:
        """Bind the kill switch late, after the orchestrator has built it (core.py)."""
        self._register = register

    def run(
        self,
        cmd: str,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """Run `cmd` via `bash -c` and return stdout, stderr, exit code and the flags.

        `cwd` defaults to the home folder (R84); a missing folder raises the
        FileNotFoundError the brain turns into a ToolError. `timeout_s` defaults to 60.
        """
        workdir = str(Path(cwd or "~").expanduser())
        timeout = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
        argv = ["bash", "-c", cmd] if not _Windows else ["cmd.exe", "/d", "/c", cmd]
        popen = subprocess.Popen(  # noqa: S603 - the argv list is the spawn, not a shell line
            argv,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=not _Windows,  # posix: the child leads its own process group
            creationflags=_WINDOWS_CTRL_C_GROUP,
        )
        unregister = self._register(popen.pid)
        timed_out = threading.Event()
        stopper = threading.Timer(timeout, self._stop, args=(popen, timed_out))
        stopper.start()
        try:
            stdout, out_overflow = self._cap(popen.stdout)
            stderr, err_overflow = self._cap(popen.stderr)
            popen.wait()
        finally:
            stopper.cancel()
            unregister()
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit": popen.returncode,
            "timed_out": timed_out.is_set(),
            "truncated": out_overflow or err_overflow,
        }

    @staticmethod
    def _cap(stream: Any) -> tuple[str, bool]:
        """Read the stream to its end, keep the first cap characters and discard the rest.

        Discarding keeps the child writing to a consumed pipe, so it finishes (and the drain
        cannot outgrow memory); an endless stream ends the same way a long command does: the
        timeout kills the group and the streams hit EOF (R84).
        """
        text = stream.read(MAX_CAPTURE + 1)
        overflow = len(text) > MAX_CAPTURE
        if overflow:
            while stream.read(MAX_CAPTURE):
                pass
        return text[:MAX_CAPTURE], overflow

    @staticmethod
    def _stop(popen: subprocess.Popen[Any], timed_out: threading.Event) -> None:
        """Kill the child and its group; the streams then hit EOF and the run returns."""
        timed_out.set()
        if _Windows:
            popen.kill()
            return
        _kill_group(popen.pid)
