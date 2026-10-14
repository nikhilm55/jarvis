"""Tie a child process's life to its parent's via Linux PR_SET_PDEATHSIG.

PDEATHSIG fires when the forking THREAD exits, not the process; callers
spawn from asyncio.to_thread workers, whose threads live until the event
loop closes, which is acceptable.
"""

import ctypes
import os
import signal
import sys
from collections.abc import Callable
from typing import Protocol

__all__ = ["parent_death_preexec"]

PR_SET_PDEATHSIG = 1


class _Libc(Protocol):
    """Protocol for a libc handle exposing prctl."""

    def prctl(self, option: int, arg2: int, arg3: int, arg4: int, arg5: int) -> int: ...


def parent_death_preexec(
    libc: _Libc | None = None, *, parent_pid: int | None = None
) -> Callable[[], None] | None:
    """Return a Popen preexec_fn that asks the kernel to SIGTERM the child when its parent dies.

    Returns None where unsupported (sys.platform != "linux").
    """
    if sys.platform != "linux":
        return None

    if libc is None:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
        except OSError:
            return None

    expected = parent_pid if parent_pid is not None else os.getpid()

    def _preexec() -> None:
        """Runs in the forked child between fork and exec."""
        if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
            os._exit(1)
        if os.getppid() != expected:
            os._exit(1)

    return _preexec
