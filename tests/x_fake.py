"""A fake X server with a window manager that answers the EWMH messages, for the window tests."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from jarvis.desktop.windows import Rect


@dataclass
class FakeWindow:
    title: str
    wm_class: tuple[str, str]
    rect: Rect
    states: set[str] = field(default_factory=set)
    types: frozenset[str] = frozenset({"NORMAL"})
    extents: tuple[int, int, int, int] = (1, 1, 28, 1)


class FakeX:
    """Implements `XPort`. With `responsive=False` the window manager ignores every message."""

    def __init__(self, monitors: Sequence[Rect] | None = None, workarea: Rect | None = None):
        self.windows: dict[int, FakeWindow] = {}  # insertion order = stacking, bottom to top
        self.active: int | None = None
        self.sent: list[tuple[int, str, tuple[int | str, ...]]] = []
        self.responsive = True
        self._monitors = list(monitors or [Rect(0, 0, 1920, 1080)])
        self._workarea = workarea or Rect(0, 27, 1920, 1053)

    def add(
        self,
        wid: int,
        title: str,
        app: str = "app",
        rect: Rect | None = None,
        *,
        states: Sequence[str] = (),
        types: Sequence[str] = ("NORMAL",),
    ) -> int:
        window_rect = rect or Rect(100, 100, 800, 600)
        window = FakeWindow(title, (app, app.title()), window_rect, set(states), frozenset(types))
        self.windows[wid] = window
        return wid

    # --- XPort reads ---
    def stacking(self) -> list[int]:
        return list(self.windows)

    def active_window(self) -> int | None:
        return self.active

    def title(self, wid: int) -> str:
        return self.windows[wid].title if wid in self.windows else ""

    def wm_class(self, wid: int) -> tuple[str, str]:
        return self.windows[wid].wm_class if wid in self.windows else ("", "")

    def window_types(self, wid: int) -> frozenset[str]:
        return self.windows[wid].types if wid in self.windows else frozenset()

    def states(self, wid: int) -> frozenset[str]:
        return frozenset(self.windows[wid].states) if wid in self.windows else frozenset()

    def rect(self, wid: int) -> Rect | None:
        return self.windows[wid].rect if wid in self.windows else None

    def frame_extents(self, wid: int) -> tuple[int, int, int, int]:
        return self.windows[wid].extents if wid in self.windows else (0, 0, 0, 0)

    def monitors(self) -> list[Rect]:
        return list(self._monitors)

    def workarea(self) -> Rect:
        return self._workarea

    def server_time(self) -> int:
        return 4242

    # --- XPort write, answered like a window manager ---
    def send(self, wid: int, message: str, data: Sequence[int | str]) -> None:
        self.sent.append((wid, message, tuple(data)))
        window = self.windows.get(wid)
        if not self.responsive or window is None:
            return
        if message == "_NET_ACTIVE_WINDOW":
            window.states.discard("HIDDEN")
            self.active = wid
            self.windows[wid] = self.windows.pop(wid)  # raised to the top
        elif message == "WM_CHANGE_STATE" and data[0] == 3:
            window.states.add("HIDDEN")
            if self.active == wid:
                self.active = None
        elif message == "_NET_CLOSE_WINDOW":
            del self.windows[wid]
            if self.active == wid:
                self.active = None
        elif message == "_NET_WM_STATE":
            self._change_state(window, data)
        elif message == "_NET_MOVERESIZE_WINDOW":
            self._move_resize(window, data)

    @staticmethod
    def _change_state(window: FakeWindow, data: Sequence[int | str]) -> None:
        action = data[0]
        for atom in data[1:3]:
            if isinstance(atom, str):
                name = atom.removeprefix("_NET_WM_STATE_")
                if action == 0 or (action == 2 and name in window.states):
                    window.states.discard(name)
                else:
                    window.states.add(name)

    @staticmethod
    def _move_resize(window: FakeWindow, data: Sequence[int | str]) -> None:
        flags = data[0]
        assert isinstance(flags, int)
        old = window.rect
        values = [v for v in data[1:5] if isinstance(v, int)]
        wanted = [bool(flags & (1 << (8 + i))) for i in range(4)]
        x, y, w, h = (values[i] if wanted[i] else (old.x, old.y, old.w, old.h)[i] for i in range(4))
        window.rect = Rect(x, y, w, h)
