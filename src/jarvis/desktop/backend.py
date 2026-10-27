"""Desktop operations (open/close apps, volume) behind injectable hooks."""

import contextlib
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager

from jarvis.config import ConfigError, load_settings
from jarvis.desktop.apps import (
    Ambiguous,
    AppEntry,
    find_app,
    load_index,
)
from jarvis.desktop.volume import (
    Runner,
    VolumeState,
    run_wpctl,
    set_mute,
    volume_get,
    volume_set,
    volume_step,
)
from jarvis.desktop.windows import WindowError, WindowManager, WindowView, XPort, make_ref
from jarvis.desktop.x11 import (
    WindowInfo,
    X11Error,
    app_matches,
    close_window,
    list_windows,
    new_windows,
)
from jarvis.desktop.xport import open_port

_OPEN_POLLS = 40
_RUNNING_POLLS = 10  # an app that was already running mostly just raises its window
_OPEN_POLL_S = 0.1


class WorkerError(Exception):
    """Raised for worker-level failures with a stable code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def configured_aliases() -> Mapping[str, str]:
    """The spoken-name aliases in the user's settings; none (and a note on stderr) if unreadable."""
    try:
        return load_settings().apps.aliases
    except ConfigError as exc:
        print(f"desktop worker: ignoring app aliases: {exc}", file=sys.stderr)
        return {}


def launch_app(app: AppEntry) -> None:
    """Launch an app via gio and wait briefly for the launcher to exit."""
    try:
        proc = subprocess.Popen(  # noqa: S603
            ["gio", "launch", str(app.path)],  # noqa: S607
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise WorkerError("UNSUPPORTED_ON_PLATFORM", "gio is not available") from exc
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return
    if proc.returncode != 0:
        raise WorkerError("INTERNAL", "gio launch failed")


class Hooks:
    """Pluggable callables so tests can inject fakes."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        entries: Callable[[], Sequence[AppEntry]] | None = None,
        aliases: Callable[[], Mapping[str, str]] | None = None,
        windows: Callable[[], list[WindowInfo]] | None = None,
        closer: Callable[[int], None] | None = None,
        launcher: Callable[[AppEntry], None] | None = None,
        runner: Runner | None = None,
        port: Callable[[], AbstractContextManager[XPort]] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.entries = entries or load_index
        self.aliases = aliases or configured_aliases
        self.windows = windows or list_windows
        self.closer = closer or close_window
        self.launcher = launcher or launch_app
        self.runner = runner or run_wpctl
        self.port = port or open_port
        self.sleep = sleep or time.sleep


class DesktopBackend:
    """High-level desktop operations driven by Hooks."""

    def __init__(self, hooks: Hooks | None = None) -> None:
        self._hooks = hooks or Hooks()

    def _resolve(self, query: str) -> AppEntry:
        result = find_app(query, self._hooks.entries(), self._hooks.aliases())
        if result is None:
            raise WorkerError("NOT_FOUND", f"no installed app matches {query!r}")
        if isinstance(result, Ambiguous):
            names = [c.name for c in result.candidates]
            joined = " and ".join(names) if len(names) == 2 else ", ".join(names)
            raise WorkerError(
                "AMBIGUOUS",
                f"found {len(names)}: {joined}. Which one?",
            )
        return result

    def open_app(self, query: str) -> dict[str, object]:
        app = self._resolve(query)
        windows = self._hooks.windows()
        before = {w.window_id for w in windows}
        running = any(app_matches(app, w) for w in windows)
        self._hooks.launcher(app)
        polls = _RUNNING_POLLS if running else _OPEN_POLLS
        fresh: list[WindowInfo] = []
        latest = windows
        for attempt in range(polls):
            latest = self._hooks.windows()
            fresh = [w for w in new_windows(before, latest) if app_matches(app, w)]
            if fresh:
                break
            if attempt < polls - 1:
                self._hooks.sleep(_OPEN_POLL_S)
        result: dict[str, object] = {
            "app": app.name,
            "window_ids_new": [w.window_id for w in fresh],
        }
        mine = fresh or [w for w in latest if app_matches(app, w)]
        result["focused"] = False  # no window yet: the app is still starting
        if mine:
            result.update(self._bring_to_front(app, [w.window_id for w in mine]))
        return result

    def _bring_to_front(self, app: AppEntry, wids: Sequence[int]) -> dict[str, object]:
        """Focus the app's frontmost window among `wids` and check it (S1): focused and in front."""
        try:
            with self._manager() as manager:
                front = next((v.wid for v in manager.list() if v.wid in wids), None)
                if front is None:  # a window of a kind the user does not see as a window
                    return {}
                view = manager.focus(make_ref(front))
        except WindowError as exc:
            raise WorkerError(
                "ACTION_FAILED", f"{app.name} opened but is not in front: {exc.message}"
            ) from exc
        except X11Error as exc:
            if exc.code == "UNSUPPORTED_ON_PLATFORM":
                return {}  # the app was launched; only the bring-to-front needs X11
            raise
        return {"focused": True, "ref": view.ref}

    def close_app(self, query: str) -> dict[str, object]:
        app = self._resolve(query)
        closed = 0
        for window in self._hooks.windows():
            if not app_matches(app, window):
                continue
            try:
                self._hooks.closer(window.window_id)
            except X11Error as exc:
                if exc.code == "NOT_FOUND":
                    continue
                raise
            closed += 1
        return {"app": app.name, "closed": closed}

    @contextlib.contextmanager
    def _manager(self) -> Iterator[WindowManager]:
        with self._hooks.port() as port:
            yield WindowManager(port, sleep=self._hooks.sleep)

    def _app_of(self, view: WindowView) -> tuple[str, str]:
        """The (name, id) of the app a window belongs to: its launcher, else its WM_CLASS."""
        info = WindowInfo(view.wid, view.wm_instance, view.wm_class, None, view.title)
        for entry in self._hooks.entries():
            if app_matches(entry, info):
                return entry.name, entry.desktop_id
        return view.wm_class, view.wm_class.casefold()

    def _describe(self, view: WindowView) -> dict[str, object]:
        name, app_id = self._app_of(view)
        return {
            "ref": view.ref,
            "title": view.title,
            "app": name,
            "app_id": app_id,
            "monitor": view.monitor,
            "state": list(view.state),
        }

    def list_windows(self) -> dict[str, object]:
        with self._manager() as manager:
            views = manager.list()
        return {"windows": [self._describe(v) for v in views]}

    def focus_window(self, ref: str) -> dict[str, object]:
        with self._manager() as manager:
            view = manager.focus(ref)
        return self._describe(view)

    def window_op(
        self, ref: str, op: str, monitor: int | None = None, with_refs: Sequence[str] = ()
    ) -> dict[str, object]:
        with self._manager() as manager:
            views = manager.apply_op(ref, op, monitor=monitor, with_targets=with_refs)
        return {"op": op, "windows": [self._describe(v) for v in views]}

    def list_apps(self) -> dict[str, object]:
        apps = [
            {"name": e.name, "id": e.desktop_id, "source": e.source} for e in self._hooks.entries()
        ]
        return {"apps": sorted(apps, key=lambda a: str(a["name"]).casefold())}

    def is_running(self, query: str) -> dict[str, object]:
        """Whether the app has a window open; an app that is not installed is judged by class."""
        windows = self._hooks.windows()
        try:
            app = self._resolve(query)
        except WorkerError as exc:
            if exc.code != "NOT_FOUND":
                raise
            wanted = query.casefold().strip()
            count = sum(
                wanted in (w.wm_class.casefold(), w.wm_instance.casefold()) for w in windows
            )
            return {"app": query, "running": count > 0, "windows": count, "installed": False}
        count = sum(app_matches(app, w) for w in windows)
        return {"app": app.name, "running": count > 0, "windows": count, "installed": True}

    def volume_get(self) -> dict[str, object]:
        state = volume_get(self._hooks.runner)
        return _state(state)

    def volume_set(self, percent: int) -> dict[str, object]:
        state = volume_set(percent, self._hooks.runner)
        return _state(state)

    def volume_step(self, delta: int) -> dict[str, object]:
        state = volume_step(delta, self._hooks.runner)
        return _state(state)

    def mute(self, on: bool) -> dict[str, object]:
        state = set_mute(on, self._hooks.runner)
        return _state(state)


def _state(state: VolumeState) -> dict[str, object]:
    return {"percent": state.percent, "muted": state.muted}
