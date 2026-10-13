"""Supervise the optional HUD window process."""

import asyncio
import contextlib
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol

from jarvis.hud.window import EXIT_NO_GUI, EXIT_USAGE, TOKEN_ENV
from jarvis.log import get_logger

logger = get_logger("hud.supervisor")

WINDOW_PATH = Path(__file__).with_name("window.py").resolve()


class HudProcess(Protocol):
    """What asyncio.subprocess.Process offers to the supervisor."""

    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


Spawn = Callable[[], Awaitable[HudProcess]]
Sleep = Callable[[float], Awaitable[None]]


class HudSupervisor:
    """Supervises the HUD window process, falling back to headless on failure."""

    def __init__(  # noqa: PLR0913 - keyword-only knobs; the clock and sleep are test seams
        self,
        spawn: Spawn,
        *,
        max_crashes: int = 3,
        window_s: float = 60.0,
        backoff_s: tuple[float, ...] = (0.5, 1.0, 2.0),
        stop_grace_s: float = 3.0,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a supervisor for the given spawn callable."""
        self._spawn = spawn
        self._max_crashes = max_crashes
        self._window_s = window_s
        self._backoff_s = backoff_s
        self._stop_grace_s = stop_grace_s
        self._sleep = sleep
        self._clock = clock
        self._headless = False
        self._stopping = False
        self._proc: HudProcess | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def headless(self) -> bool:
        """True once the supervisor gave up on the HUD window."""
        return self._headless

    async def start(self) -> None:
        """Create the supervising task; a second call raises RuntimeError."""
        if self._task is not None:
            raise RuntimeError("supervisor already started")
        self._task = asyncio.create_task(self._supervise())

    async def wait(self) -> None:
        """Await the supervising task until it ends."""
        if self._task is not None:
            await self._task

    async def stop(self) -> None:
        """Stop the supervisor and the HUD process; idempotent."""
        self._stopping = True
        await self._terminate_proc()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _supervise(self) -> None:
        """Run the supervise loop until the HUD is closed or we give up."""
        crashes: list[float] = []
        while True:
            try:
                proc = await self._spawn()
            except OSError as error:
                logger.warning("HUD window cannot start (%s); running without a HUD", error)
                self._headless = True
                return
            self._proc = proc
            code = await proc.wait()
            self._proc = None
            if self._stopping or self._should_stop_after(code, crashes):
                return
            await self._sleep(self._backoff_s[min(len(crashes) - 1, len(self._backoff_s) - 1)])
            if self._stopping:
                return

    def _should_stop_after(self, code: int, crashes: list[float]) -> bool:
        """Log the exit and say whether to stop supervising; a crash is added to `crashes`."""
        if code == 0:
            logger.info("HUD window closed")
            return True
        if code == EXIT_NO_GUI:
            logger.warning(
                "HUD unavailable (GTK 3 / WebKit2 / a display is missing); running without a HUD"
            )
            self._headless = True
            return True
        if code == EXIT_USAGE:
            logger.error("HUD window refused to start (exit 2); running without a HUD")
            self._headless = True
            return True
        now = self._clock()
        crashes[:] = [t for t in crashes if now - t < self._window_s]
        crashes.append(now)
        if len(crashes) > self._max_crashes:
            logger.error(
                "HUD window crashed %d times within %.0fs; giving up",
                len(crashes),
                self._window_s,
            )
            self._headless = True
            return True
        logger.warning("HUD window exited with code %d; restarting", code)
        return False

    async def _terminate_proc(self) -> None:
        """Terminate the HUD process, killing it if it ignores the signal."""
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), self._stop_grace_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()


_ENV_NAMES = frozenset(
    {
        "DISPLAY",
        "XAUTHORITY",
        "WAYLAND_DISPLAY",
        "HOME",
        "USER",
        "LANG",
        "PATH",
        "DBUS_SESSION_BUS_ADDRESS",
    }
)
_ENV_PREFIXES = ("LC_", "XDG_")


def window_env(token: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a minimal env for the HUD window child so no API keys or stale token leak."""
    source = os.environ if environ is None else environ
    env = {
        name: value
        for name, value in source.items()
        if name in _ENV_NAMES or name.startswith(_ENV_PREFIXES)
    }
    env[TOKEN_ENV] = token
    return env


def window_spawner(
    python: str,
    url: str,
    token: str,
    exec_fn: Callable[..., Awaitable[HudProcess]] = asyncio.create_subprocess_exec,
) -> Spawn:
    """Return a spawn callable that launches the HUD window process."""

    async def spawn() -> HudProcess:
        """Launch the HUD window process with the token in the environment."""
        return await exec_fn(
            python,
            "-I",
            str(WINDOW_PATH),
            "--url",
            url,
            env=window_env(token),
            stdin=asyncio.subprocess.DEVNULL,
        )

    return spawn
