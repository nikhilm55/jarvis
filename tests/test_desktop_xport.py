"""The python-xlib adapter: property decoding and message packing, against a stand-in display."""

from types import SimpleNamespace
from typing import Any

import pytest
from Xlib import X, error
from Xlib.ext import randr
from Xlib.protocol import event

from jarvis.desktop import xport
from jarvis.desktop.windows import Rect
from jarvis.desktop.x11 import X11Error
from jarvis.desktop.xport import XlibPort, pack_data


class Gone(error.XError):  # type: ignore[misc]
    """A BadWindow without the wire data XError wants to parse."""

    def __init__(self) -> None:
        Exception.__init__(self, "BadWindow")


class FakeProp:
    def __init__(self, value: list[int]) -> None:
        self.value = value


class FakeWindow:
    def __init__(self, display: "FakeDisplay", wid: int) -> None:
        self.id = wid
        self._display = display

    def get_full_property(self, atom: int, _kind: int) -> FakeProp | None:
        name = self._display.atom_names[atom]
        if (self.id, name) in self._display.gone:
            raise Gone
        value = self._display.props.get((self.id, name))
        return None if value is None else FakeProp(value)

    def get_wm_name(self) -> str | None:
        return self._display.legacy_names.get(self.id)

    def get_wm_class(self) -> tuple[str, str] | None:
        return self._display.classes.get(self.id)

    def get_geometry(self) -> SimpleNamespace:
        return SimpleNamespace(width=640, height=480)

    def translate_coords(self, src: "FakeWindow", _x: int, _y: int) -> SimpleNamespace:
        return SimpleNamespace(x=src.id % 1000, y=src.id // 1000)


class FakeDisplay:
    """Just enough of Display: atoms, properties by (window, name), a root window."""

    def __init__(self) -> None:
        self.atom_ids: dict[str, int] = {}
        self.atom_names: dict[int, str] = {}
        self.props: dict[tuple[int, str], list[int]] = {}
        self.legacy_names: dict[int, str] = {}
        self.classes: dict[int, tuple[str, str]] = {}
        self.gone: set[tuple[int, str]] = set()
        self.randr = True
        self.root = FakeWindow(self, 1)

    def intern_atom(self, name: str) -> int:
        atom = self.atom_ids.setdefault(name, 100 + len(self.atom_ids))
        self.atom_names[atom] = name
        return atom

    def get_atom_name(self, atom: int) -> str:
        return self.atom_names[atom]

    def create_resource_object(self, _kind: str, wid: int) -> FakeWindow:
        return FakeWindow(self, wid)

    def screen(self) -> SimpleNamespace:
        return SimpleNamespace(root=self.root)

    def has_extension(self, name: str) -> bool:
        return name == "RANDR" and self.randr

    def set(self, wid: int | None, name: str, *values: int | str) -> None:
        ints = [self.intern_atom(v) if isinstance(v, str) else v for v in values]
        self.props[(1 if wid is None else wid, name)] = ints


def port(display: FakeDisplay) -> XlibPort:
    return XlibPort(display)


def test_should_pack_five_unsigned_words_naming_atoms_and_wrapping_negatives() -> None:
    ids = {"_NET_WM_STATE_FULLSCREEN": 7}
    assert pack_data([1, "_NET_WM_STATE_FULLSCREEN", -1], ids.__getitem__) == [
        1,
        7,
        0xFFFFFFFF,
        0,
        0,
    ]
    assert pack_data([1, 2, 3, 4, 5, 6, 7], ids.__getitem__) == [1, 2, 3, 4, 5]
    assert pack_data([], ids.__getitem__) == [0, 0, 0, 0, 0]


def test_should_read_the_stacking_order_and_fall_back_to_the_client_list() -> None:
    d = FakeDisplay()
    d.set(None, "_NET_CLIENT_LIST", 5, 6)
    assert port(d).stacking() == [5, 6]
    d.set(None, "_NET_CLIENT_LIST_STACKING", 6, 5)
    assert port(d).stacking() == [6, 5]


def test_should_read_the_active_window_and_treat_zero_as_none() -> None:
    d = FakeDisplay()
    assert port(d).active_window() is None
    d.set(None, "_NET_ACTIVE_WINDOW", 0)
    assert port(d).active_window() is None
    d.set(None, "_NET_ACTIVE_WINDOW", 42)
    assert port(d).active_window() == 42


def test_should_name_window_states_and_types_without_their_prefix() -> None:
    d = FakeDisplay()
    d.set(9, "_NET_WM_STATE", "_NET_WM_STATE_HIDDEN", "_NET_WM_STATE_MAXIMIZED_VERT")
    d.set(9, "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK")
    p = port(d)
    assert p.states(9) == {"HIDDEN", "MAXIMIZED_VERT"}
    assert p.window_types(9) == {"DOCK"}
    assert p.states(10) == frozenset()


def test_should_give_empty_answers_for_a_window_that_is_gone() -> None:
    d = FakeDisplay()
    d.gone.add((9, "_NET_WM_STATE"))
    assert port(d).states(9) == frozenset()


def test_should_read_the_title_from_the_utf8_name_then_the_legacy_one() -> None:
    d = FakeDisplay()
    d.legacy_names[9] = "old"
    assert port(d).title(9) == "old"
    d.props[(9, "_NET_WM_NAME")] = list("héllo".encode())
    d.intern_atom("_NET_WM_NAME")
    assert port(d).title(9) == "héllo"
    assert port(d).title(10) == ""


def test_should_read_the_window_class_as_instance_and_class() -> None:
    d = FakeDisplay()
    d.classes[9] = ("calc", "Calc")
    assert port(d).wm_class(9) == ("calc", "Calc")
    assert port(d).wm_class(10) == ("", "")


def test_should_report_the_client_area_in_root_coordinates() -> None:
    assert port(FakeDisplay()).rect(5007) == Rect(7, 5, 640, 480)


def test_should_read_frame_extents_as_left_right_top_bottom_or_zeros() -> None:
    d = FakeDisplay()
    d.set(9, "_NET_FRAME_EXTENTS", 1, 2, 28, 3)
    assert port(d).frame_extents(9) == (1, 2, 28, 3)
    d.set(10, "_NET_FRAME_EXTENTS", 1, 2)
    assert port(d).frame_extents(10) == (0, 0, 0, 0)


def test_should_use_the_workarea_of_the_current_desktop() -> None:
    d = FakeDisplay()
    d.set(None, "_NET_WORKAREA", 0, 27, 1920, 1053, 0, 30, 1920, 1050)
    d.set(None, "_NET_CURRENT_DESKTOP", 1)
    assert port(d).workarea() == Rect(0, 30, 1920, 1050)
    d.set(None, "_NET_CURRENT_DESKTOP", 0)
    assert port(d).workarea() == Rect(0, 27, 1920, 1053)


def test_should_sort_monitors_left_to_right_and_fall_back_to_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mon(x: int, y: int) -> SimpleNamespace:
        return SimpleNamespace(x=x, y=y, width_in_pixels=100, height_in_pixels=50)

    d = FakeDisplay()
    monkeypatch.setattr(
        randr,
        "get_monitors",
        lambda _root: SimpleNamespace(monitors=[mon(100, 0), mon(0, 0)]),
    )
    assert port(d).monitors() == [Rect(0, 0, 100, 50), Rect(100, 0, 100, 50)]
    d.randr = False
    assert port(d).monitors() == [Rect(0, 0, 640, 480)]  # the root window's size


class Sent:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.synced = 0


def test_should_send_a_32_bit_client_message_to_the_root_with_redirect_rights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = FakeDisplay()
    sent = Sent()

    def send_event(ev: Any, event_mask: int, onerror: Any = None) -> None:
        sent.events.append((ev, event_mask))

    d.root.send_event = send_event  # type: ignore[attr-defined]
    d.sync = lambda: setattr(sent, "synced", sent.synced + 1)  # type: ignore[attr-defined]
    monkeypatch.setattr(event, "ClientMessage", lambda **kw: kw)
    port(d).send(9, "_NET_ACTIVE_WINDOW", [2, 123, "_NET_WM_STATE_HIDDEN"])
    ((message, mask),) = sent.events
    assert mask == X.SubstructureRedirectMask | X.SubstructureNotifyMask
    assert message["client_type"] == d.atom_ids["_NET_ACTIVE_WINDOW"]
    assert message["data"] == (32, [2, 123, d.atom_ids["_NET_WM_STATE_HIDDEN"], 0, 0])
    assert message["window"].id == 9
    assert sent.synced == 1


def test_should_refuse_a_wayland_session_with_the_way_to_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")  # XWayland is there, but it would show only some windows
    with pytest.raises(X11Error) as info, xport.open_port():
        pass
    assert info.value.code == "UNSUPPORTED_ON_PLATFORM"
    assert "Ubuntu on Xorg" in info.value.message
    assert "log out" in info.value.message.casefold()


def test_should_say_there_is_no_x11_when_there_is_no_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(X11Error) as info, xport.open_port():
        pass
    assert info.value.code == "UNSUPPORTED_ON_PLATFORM"
