"""The orchestrator: the loop's lifecycle, joining capture, listener and turn runner (FRS 4.2)."""

import asyncio
import signal
from collections.abc import Callable, Coroutine
from typing import Protocol

from jarvis.activity import ActivityLog
from jarvis.config import Settings
from jarvis.consent.broker import Broker
from jarvis.killswitch import KillSwitch
from jarvis.log import get_logger
from jarvis.orchestrator.capture import Capture, CaptureItem, SourceEnded, SourceFailed
from jarvis.orchestrator.components import Components, close_components, start_components
from jarvis.orchestrator.hud import HudEvent, HudSink, null_sink, safe_sink
from jarvis.orchestrator.listener import Listener, ListenerServices
from jarvis.orchestrator.segmenter import Segment, SpeechStarted
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.turns import Command, TurnRunner, TurnServices
from jarvis.orchestrator.windows import Windows
from jarvis.policy import Mode

__all__ = ["Orchestrator"]

logger = get_logger(__name__)

_DRAIN_S = 5.0  # longest shutdown waits for an in-flight transcription


class HotkeyPort(Protocol):
    """The kill-switch hotkey (`jarvis.hotkey.Hotkey`); its callback runs on its own thread."""

    def start(self) -> bool: ...

    def stop(self) -> None: ...


HotkeyFactory = Callable[[Callable[[], None]], HotkeyPort]


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
        hotkey: HotkeyFactory | None = None,
    ) -> None:
        """Wire the components and prepare the shared state."""
        self._settings = settings
        self._parts = parts
        self._mode = mode
        hud = self._hud = safe_sink(hud)  # a broken HUD never stops start-up or a timer
        self._activity = activity or ActivityLog()
        self._timing = timing or Timing.from_settings(settings)
        self._windows = Windows()
        self._commands: asyncio.Queue[Command] = asyncio.Queue()
        self._items: asyncio.Queue[Segment | SourceEnded | SourceFailed] = asyncio.Queue()
        self._stopping = asyncio.Event()
        self._touched = asyncio.Event()
        self._current: asyncio.Task[None] | None = None
        self._capture: Capture | None = None
        self._hotkey_factory = hotkey
        self._background: set[asyncio.Task[None]] = set()
        self.killswitch = KillSwitch(self._stop_turn)  # FR-SAFE-04: voice, hotkey and HUD Stop
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
            consent=parts.consent,
            grants=parts.grants,
            answers=parts.answers,
            consent_admin=parts.consent if isinstance(parts.consent, Broker) else None,
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
            stop=lambda: self.killswitch.trigger("voice"),
            barge_in=parts.barge_in,
        )
        self._listener = Listener(listener_services)

    async def run(self) -> None:
        """Run until the source ends, a stop is requested or startup fails."""
        loop = asyncio.get_running_loop()
        installed = self._install_signals(loop)
        tasks: list[asyncio.Task[None]] = []
        hotkey = self._start_hotkey(loop)
        try:
            await self._start()
            capture = Capture(
                self._parts.source,
                self._parts.segmenter,
                loop,
                self._on_capture,
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
            if hotkey is not None:
                await asyncio.to_thread(hotkey.stop)
            await self._shutdown(tasks)

    def _start_hotkey(self, loop: asyncio.AbstractEventLoop) -> HotkeyPort | None:
        """Grab Ctrl+Alt+Esc (R89/R103); a press triggers the kill switch on the loop."""
        if self._hotkey_factory is None:
            return None

        def pressed() -> None:  # on the hotkey's thread
            loop.call_soon_threadsafe(self._spawn, self.killswitch.trigger("hotkey"))

        hotkey = self._hotkey_factory(pressed)
        return hotkey if hotkey.start() else None

    def _spawn(self, work: Coroutine[object, object, None]) -> None:
        """Run `work` in the background, keeping a reference until it ends."""
        task = asyncio.get_running_loop().create_task(work)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def request_stop(self) -> None:
        """Ask the loop to stop after the current work settles."""
        self._stopping.set()

    def _install_signals(self, loop: asyncio.AbstractEventLoop) -> list[int]:
        """Install SIGINT, SIGTERM and SIGHUP (terminal closed) handlers where supported."""
        installed: list[int] = []
        for name in ("SIGINT", "SIGTERM", "SIGHUP"):  # SIGHUP does not exist on Windows
            sig = getattr(signal, name, None)
            if sig is None:
                continue
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

    def _on_capture(self, item: CaptureItem) -> None:
        """Take one item from the capture thread, on the loop (via call_soon_threadsafe)."""
        if isinstance(item, SpeechStarted):
            # Speech that began inside an open window keeps it open until that speech ends.
            self._windows.hold_if_open(item.at)
        else:
            self._items.put_nowait(item)

    def _submit(self, command: Command) -> None:
        """Queue a command for the serial turn worker."""
        self._commands.put_nowait(command)
        self._touched.set()  # a new turn restarts the inactivity period

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
            self._spawn(self._rewarm(task))
        self._parts.voice.earcon("done")
        await self._hud(HudEvent("idle"))

    async def _rewarm(self, cancelled: asyncio.Task[None]) -> None:
        """A cancelled brain turn kills claude; start the next one now, not on the next turn."""
        brain = self._parts.brain
        if brain is None:
            return
        await asyncio.gather(cancelled, return_exceptions=True)
        try:
            await brain.start()
        except Exception:
            logger.warning("re-warming the brain after a stop failed", exc_info=True)

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
            if self._current is not None or not self._commands.empty():
                continue  # a turn is running or queued: its context must not be wiped (R52)
            try:
                await brain.reset()
            except Exception:
                logger.exception("brain reset failed")
            finally:
                if self._parts.grants is not None:
                    self._parts.grants.end("brain_reset")  # session grants die with the session

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
        # whisper-server must not be closed under a request still in flight (R30)
        await self._listener.drain(_DRAIN_S)
        await close_components(self._parts)
