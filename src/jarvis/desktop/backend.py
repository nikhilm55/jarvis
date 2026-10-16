"""Desktop operations (open/close apps, volume) behind injectable hooks."""

import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence

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
from jarvis.desktop.x11 import (
    WindowInfo,
    X11Error,
    app_matches,
    close_window,
    list_windows,
    new_windows,
)

_OPEN_POLLS = 40
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
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.entries = entries or load_index
        self.aliases = aliases or configured_aliases
        self.windows = windows or list_windows
        self.closer = closer or close_window
        self.launcher = launcher or launch_app
        self.runner = runner or run_wpctl
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
        before = {w.window_id for w in self._hooks.windows()}
        self._hooks.launcher(app)
        fresh: list[WindowInfo] = []
        for attempt in range(_OPEN_POLLS):
            fresh = [w for w in new_windows(before, self._hooks.windows()) if app_matches(app, w)]
            if fresh:
                break
            if attempt < _OPEN_POLLS - 1:
                self._hooks.sleep(_OPEN_POLL_S)
        return {"app": app.name, "window_ids_new": [w.window_id for w in fresh]}

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
