"""Tests for jarvis.desktop.x11 EWMH window helpers (no real display)."""

import array
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from Xlib import X, error

from jarvis.desktop.apps import AppEntry
from jarvis.desktop.x11 import (
    WindowInfo,
    X11Error,
    app_matches,
    close_window,
    list_windows,
    new_windows,
    open_display,
)


class _Gone(error.XError):  # type: ignore[misc]
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


class _Prop:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeWindow:
    def __init__(
        self,
        wid: int,
        wm_class: tuple[str, str] | None,
        pid: int | None,
        title: bytes | None,
    ) -> None:
        self.id = wid
        self._wm_class = wm_class
        self._pid = pid
        self._title = title

    def __window__(self) -> int:
        return self.id

    def get_wm_class(self) -> tuple[str, str] | None:
        return self._wm_class

    def get_full_property(self, atom: int, _type: int) -> _Prop | None:
        if atom == 1001:
            if self._pid is None:
                return None
            return _Prop(array.array("i", [self._pid]))
        if atom == 1002:
            if self._title is None:
                return None
            return _Prop(self._title)
        return None


class FakeRoot:
    def __init__(self, client_list: list[int] | None, windows: Mapping[int, FakeWindow]) -> None:
        self._client_list = client_list
        self._windows = windows
        self.sent: list[tuple[Any, int]] = []

    def get_full_property(self, atom: int, _type: int) -> _Prop | None:
        if atom == 1000:
            if self._client_list is None:
                return None
            return _Prop(array.array("i", self._client_list))
        return None

    def send_event(self, ev: Any, event_mask: int) -> None:
        self.sent.append((ev, event_mask))


class _Screen:
    def __init__(self, root: FakeRoot) -> None:
        self.root = root


class FakeDisplay:
    def __init__(self, client_list: list[int] | None, windows: Mapping[int, FakeWindow]) -> None:
        self._atoms: dict[str, int] = {}
        self._windows = windows
        self._root = FakeRoot(client_list, windows)
        self.closed = False
        self.flushed = False

    def intern_atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = 1000 + len(self._atoms)
        return self._atoms[name]

    def screen(self) -> _Screen:
        return _Screen(self._root)

    def create_resource_object(self, _kind: str, wid: int) -> FakeWindow:
        return self._windows[wid]

    def close(self) -> None:
        self.closed = True

    def flush(self) -> None:
        self.flushed = True


CALC = "org.gnome.Calculator"
CALC_EXEC = "gnome-calculator %U"


def _mk_app(
    startup_wm_class: str,
    desktop_id: str,
    exec_line: str,
) -> AppEntry:
    return AppEntry(
        f"{desktop_id}.desktop",
        "X",
        "X",
        (),
        exec_line,
        startup_wm_class,
        Path("/bin/x"),
    )


def _mk_win(wm_instance: str, wm_class: str) -> WindowInfo:
    return WindowInfo(1, wm_instance, wm_class, None, "t")


@pytest.mark.parametrize(
    ("startup_wm_class", "desktop_id", "exec_line", "window", "expected"),
    [
        ("Firefox", "x", "x", ("firefox", "Firefox"), True),
        ("Firefox", "x", "x", ("other", "firefox"), True),
        ("Firefox", CALC, CALC_EXEC, (CALC, CALC), False),
        ("", CALC, CALC_EXEC, (CALC, CALC), True),
        ("", CALC, CALC_EXEC, ("other", "gnome-calculator"), True),
        ("", CALC, CALC_EXEC, ("unrelated", "unrelated"), False),
        ("", "", "", ("", ""), False),
    ],
)
def test_should_match_when_app_matches_criteria(
    startup_wm_class: str,
    desktop_id: str,
    exec_line: str,
    window: tuple[str, str],
    expected: bool,
) -> None:
    app = _mk_app(startup_wm_class, desktop_id, exec_line)
    win = _mk_win(*window)
    assert app_matches(app, win) is expected


def test_should_return_new_windows_when_diffing() -> None:
    before = [1, 2]
    now = [
        WindowInfo(1, "a", "a", None, ""),
        WindowInfo(3, "b", "b", None, ""),
        WindowInfo(2, "c", "c", None, ""),
    ]
    result = new_windows(before, now)
    assert [w.window_id for w in result] == [3]


def test_should_keep_order_when_new_windows() -> None:
    before = [1]
    now = [
        WindowInfo(3, "a", "a", None, ""),
        WindowInfo(5, "b", "b", None, ""),
        WindowInfo(7, "c", "c", None, ""),
    ]
    result = new_windows(before, now)
    assert [w.window_id for w in result] == [3, 5, 7]


def test_should_return_all_when_before_empty() -> None:
    now = [WindowInfo(1, "a", "a", None, ""), WindowInfo(2, "b", "b", None, "")]
    result = new_windows([], now)
    assert [w.window_id for w in result] == [1, 2]


def test_should_parse_window_fields_when_list_windows() -> None:
    windows = {1: FakeWindow(1, ("inst", "cls"), 42, b"Caf\xc3\xa9")}
    disp = FakeDisplay([1], windows)
    result = list_windows(disp)
    assert len(result) == 1
    w = result[0]
    assert w.window_id == 1
    assert w.wm_instance == "inst"
    assert w.wm_class == "cls"
    assert w.pid == 42
    assert w.title == "Café"


def test_should_return_none_pid_when_missing() -> None:
    windows = {1: FakeWindow(1, ("i", "c"), None, b"t")}
    disp = FakeDisplay([1], windows)
    result = list_windows(disp)
    assert result[0].pid is None


def test_should_return_empty_strings_when_wm_class_missing() -> None:
    windows = {1: FakeWindow(1, None, 1, b"t")}
    disp = FakeDisplay([1], windows)
    result = list_windows(disp)
    assert result[0].wm_instance == ""
    assert result[0].wm_class == ""


def test_should_return_empty_list_when_client_list_missing() -> None:
    disp = FakeDisplay(None, {})
    result = list_windows(disp)
    assert result == []


def test_should_skip_window_when_read_raises() -> None:
    class GoneWindow(FakeWindow):
        def get_wm_class(self) -> tuple[str, str] | None:
            raise _Gone()

    windows = {1: GoneWindow(1, None, None, None)}
    disp = FakeDisplay([1], windows)
    result = list_windows(disp)
    assert result == []


def test_should_not_close_passed_display_when_list_windows() -> None:
    windows = {1: FakeWindow(1, ("i", "c"), 1, b"t")}
    disp = FakeDisplay([1], windows)
    list_windows(disp)
    assert disp.closed is False


def test_should_raise_when_display_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(X11Error) as exc:
        open_display()
    assert exc.value.code == "UNSUPPORTED_ON_PLATFORM"


def test_should_send_close_message_when_close_window() -> None:
    windows = {1: FakeWindow(1, ("i", "c"), 1, b"t")}
    disp = FakeDisplay([1], windows)
    close_window(1, disp)
    assert len(disp._root.sent) == 1
    ev, mask = disp._root.sent[0]
    assert ev.client_type == disp.intern_atom("_NET_CLOSE_WINDOW")
    assert mask == X.SubstructureRedirectMask | X.SubstructureNotifyMask
    assert disp.flushed is True
