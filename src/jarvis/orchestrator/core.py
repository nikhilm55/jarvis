"""The orchestrator: the loop's lifecycle, joining capture, listener and turn runner (FRS 4.2)."""

import asyncio
import signal

from jarvis.activity import ActivityLog
from jarvis.config import Settings
from jarvis.log import get_logger
from jarvis.orchestrator.capture import Capture, CaptureItem, SourceEnded, SourceFailed
from jarvis.orchestrator.components import Components, close_components, start_components
from jarvis.orchestrator.hud import HudEvent, HudSink, null_sink
from jarvis.orchestrator.listener import Listener, ListenerServices
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.turns import Command, TurnRunner, TurnServices
from jarvis.orchestrator.windows import Windows
from jarvis.policy import Mode

__all__ = ["Orchestrator"]

logger = get_logger(__name__)


class Orchestrator:
    """Runs the capture loop, the listener and the serial turn worker."""

    def __init__(  # noqa: PLR0913 - keyword-only seams for tests
        self,
        settings: Settings,
        parts: Components,
        *,
        mode: Mode = "balanced",
        hud: HudSink = null_sink,
        activity: ActivityLog | None = None,
        timing: Timing | None = None,
    ) -> None:
        """Wire the components and prepare the shared state."""
        self._settings = settings
        self._parts = parts
        self._mode = mode
        self._hud = hud
        self._activity = activity or ActivityLog()
        self._timing = timing or Timing.from_settings(settings)
        self._windows = Windows()
        self._commands: asyncio.Queue[Command] = asyncio.Queue()
        self._items: asyncio.Queue[CaptureItem] = asyncio.Queue()
        self._stopping = asyncio.Event()
        self._touched = asyncio.Event()
        self._current: asyncio.Task[None] | None = None
        self._capture: Capture | None = None
        turn_services = TurnServices(
            settings=settings,
            mode=mode,
            desktop=parts.desktop,
            brain=parts.brain,
            voice=parts.voice,
            hud=hud,
            activity=self._activity,
            timing=self._timing,
            windows=self._windows,
            trace=parts.trace,
        )
        self._runner = TurnRunner(turn_services)
        listener_services = ListenerServices(
            settings=settings,
            transcriber=parts.transcriber,
            voice=parts.voice,
            windows=self._windows,
            hud=hud,
            activity=self._activity,
            timing=self._timing,
            submit=self._submit,
            stop=self._stop_turn,
        )
        self._listener = Listener(listener_services)

    async def run(self) -> None:
        """Run until the source ends, a stop is requested or startup fails."""
        loop = asyncio.get_running_loop()
        installed = self._install_signals(loop)
        tasks: list[asyncio.Task[None]] = []
        try:
            await self._start()
            capture = Capture(
                self._parts.source,
                self._parts.segmenter,
                loop,
                self._items.put_nowait,
            )
            self._capture = capture
            capture.start()
            tasks = [
                loop.create_task(self._turn_worker()),
                loop.create_task(self._watch_idle()),
            ]
            await self._serve()
        finally:
            for sig in installed:
                loop.remove_signal_handler(sig)
            await self._shutdown(tasks)

    def request_stop(self) -> None:
        """Ask the loop to stop after the current work settles."""
        self._stopping.set()

    def _install_signals(self, loop: asyncio.AbstractEventLoop) -> list[int]:
        """Install SIGINT and SIGTERM handlers, skipping unsupported platforms."""
        installed: list[int] = []
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except (NotImplementedError, ValueError, RuntimeError):
                continue
            installed.append(sig)
        return installed

    async def _start(self) -> None:
        """Purge old activity, warm every child, and report an unavailable brain."""
        self._activity.purge(self._settings.log.retention_days)
        problem = await start_components(self._parts)
        if problem is not None:
            await self._hud(HudEvent("error", str(problem)))
        await self._hud(HudEvent("idle"))

    async def _serve(self) -> None:
        """Consume capture items until the source ends or a stop is requested."""
        consumer = asyncio.create_task(self._consume())
        stopper = asyncio.create_task(self._stopping.wait())
        drain: asyncio.Task[None] | None = None
        try:
            await asyncio.wait({consumer, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if consumer.done() and not self._stopping.is_set():
                consumer.result()
            drain = asyncio.create_task(self._commands.join())
            await asyncio.wait({drain, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (consumer, stopper, drain):
                if task is not None:
                    task.cancel()
            pending = [t for t in (consumer, stopper, drain) if t is not None]
            await asyncio.gather(*pending, return_exceptions=True)

    async def _consume(self) -> None:
        """Take capture items and hand segments to the listener one at a time."""
        while True:
            item = await self._items.get()
            if isinstance(item, SourceFailed):
                raise item.error
            if isinstance(item, SourceEnded):
                return
            try:
                await self._listener.handle(item)
            except Exception:
                logger.exception("segment handling failed")

    def _submit(self, command: Command) -> None:
        """Queue a command for the serial turn worker."""
        self._commands.put_nowait(command)

    async def _turn_worker(self) -> None:
        """Run queued commands one at a time, remembering the current task."""
        while True:
            command = await self._commands.get()
            task = asyncio.create_task(self._runner.run(command))
            self._current = task
            try:
                await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception:
                logger.exception("turn crashed")
            finally:
                self._current = None
                self._commands.task_done()
                self._touched.set()

    async def _stop_turn(self) -> None:
        """Cancel the current turn, drop queued commands and reset the HUD."""
        self._windows.close()
        while True:
            try:
                self._commands.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self._commands.task_done()
        self._parts.voice.cancel_all()
        task = self._current
        if task is not None and not task.done():
            task.cancel()
        self._parts.voice.earcon("done")
        await self._hud(HudEvent("idle"))

    async def _watch_idle(self) -> None:
        """Reset the brain after an inactivity period with no new turn."""
        brain = self._parts.brain
        if brain is None:
            return
        while True:
            await self._touched.wait()
            while True:
                self._touched.clear()
                try:
                    await asyncio.wait_for(
                        self._touched.wait(),
                        self._timing.inactivity_reset_s,
                    )
                except TimeoutError:
                    break
            try:
                await brain.reset()
            except Exception:
                logger.exception("brain reset failed")

    async def _shutdown(self, tasks: list[asyncio.Task[None]]) -> None:
        """Stop the worker tasks, capture thread and close every child."""
        self._stopping.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._windows.close()
        self._parts.voice.cancel_all()
        if self._current is not None:
            self._current.cancel()
            await asyncio.gather(self._current, return_exceptions=True)
        if self._capture is not None:
            self._capture.stop()
            await asyncio.to_thread(self._capture.join, 5.0)
        await close_components(self._parts)
