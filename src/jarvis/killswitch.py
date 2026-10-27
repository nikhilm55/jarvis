"""The kill switch (FR-SAFE-04): one call stops everything Jarvis is doing, from any source.

"Jarvis, stop", the `Ctrl+Alt+Esc` hotkey and the HUD's Stop button all land in
`KillSwitch.trigger`. It kills the registered process groups (shell children, task 8) first,
since they run outside the event loop, then stops the turn: cancels it, drops queued commands
and silences speech. Every trigger is audited with its source.
"""

import contextlib
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Literal

from jarvis.log import audit, get_logger

__all__ = ["KillSwitch", "Source"]

Source = Literal["voice", "hotkey", "hud"]
logger = get_logger("killswitch")


def _kill_group(pgid: int) -> None:
    if sys.platform == "win32":  # no process groups; the shell tool kills its own tree there
        return
    with contextlib.suppress(ProcessLookupError):  # it ended on its own
        os.killpg(pgid, signal.SIGKILL)


class KillSwitch:
    """Stops the running turn and every process group registered for it."""

    def __init__(
        self,
        stop: Callable[[], Awaitable[None]],
        *,
        kill_group: Callable[[int], None] = _kill_group,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the orchestrator's stop; `kill_group` and `clock` are test seams."""
        self._stop = stop
        self._kill_group = kill_group
        self._clock = clock
        self._groups: set[int] = set()

    def register_process(self, pgid: int) -> Callable[[], None]:
        """Have `pgid` killed by the next trigger; call the result once the group has ended."""
        self._groups.add(pgid)
        return lambda: self._groups.discard(pgid)

    async def trigger(self, source: Source) -> None:
        """Stop everything now. Never raises: a stop that fails half-way still does the rest."""
        started = self._clock()
        groups, self._groups = sorted(self._groups), set()
        for pgid in groups:
            try:
                self._kill_group(pgid)
            except OSError:
                logger.exception("could not kill a process group", extra={"pgid": pgid})
        try:
            await self._stop()
        except Exception:
            logger.exception("stopping the turn failed", extra={"source": source})
        ms = int((self._clock() - started) * 1000)
        try:
            audit("killswitch", "kill switch", trigger=source, groups=len(groups), ms=ms)
        except Exception:
            logger.exception("kill switch audit failed", extra={"source": source})
