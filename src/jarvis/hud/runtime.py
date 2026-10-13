"""HUD runtime: single place that starts/stops the HUD for `jarvis run`."""

import contextlib
from collections.abc import AsyncIterator, Callable

from jarvis.config import HudSettings
from jarvis.hud.server import HudServer
from jarvis.hud.supervisor import HudSupervisor, Spawn, window_spawner
from jarvis.log import get_logger
from jarvis.orchestrator.hud import HudSink

SpawnerFactory = Callable[[str, str, str], Spawn]

_logger = get_logger("hud.runtime")


@contextlib.asynccontextmanager
async def running_hud(
    hud: HudSettings,
    *,
    enabled: bool = True,
    spawner: SpawnerFactory = window_spawner,
) -> AsyncIterator[HudSink | None]:
    """Yield a HUD sink (or None) for the lifetime of the HUD."""
    if not enabled or not hud.enabled:
        yield None
        return

    server = HudServer()
    try:
        await server.start()
    except (OSError, RuntimeError, TimeoutError) as error:
        _logger.warning("HUD events server could not start (%s); running without a HUD", error)
        yield None
        return

    supervisor = HudSupervisor(spawner(hud.python, server.url, server.token))
    try:
        await supervisor.start()
        yield server.publish
    finally:
        await supervisor.stop()
        await server.close()
