import importlib.util
import types
from pathlib import Path
from typing import Any

import pytest

from jarvis.hud.page import read_page

WINDOW_PATH = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "hud" / "window.py"


def _load_window() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("hud_window", WINDOW_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeX11:
    def __init__(self, no_display: bool = False) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._no_display = no_display

    def XOpenDisplay(self, arg: Any) -> int:
        self.calls.append(("XOpenDisplay", (arg,)))
        return 0 if self._no_display else 77

    def XFlush(self, display: int) -> None:
        self.calls.append(("XFlush", (display,)))

    def XCloseDisplay(self, display: int) -> None:
        self.calls.append(("XCloseDisplay", (display,)))


class FakeXext:
    def __init__(self, boom: bool = False) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._boom = boom

    def XShapeCombineRectangles(self, *args: Any) -> None:
        self.calls.append(args)
        if self._boom:
            raise RuntimeError("boom")


def test_should_not_have_title_signalling_or_passthrough_when_source_is_loaded() -> None:
    text = WINDOW_PATH.read_text(encoding="utf-8")
    for token in (
        "notify::title",
        "_on_title",
        "visible_from_title",
        "TITLE_PREFIX",
        "set_pass_through",
    ):
        assert token not in text
    module = _load_window()
    assert not hasattr(module, "visible_from_title")
    assert not hasattr(module, "TITLE_PREFIX")


def test_should_not_announce_visibility_when_page_is_read() -> None:
    page = read_page()
    assert "document.title" not in page
    assert "announce" not in page


def test_should_return_true_and_call_shape_when_fakes_are_provided() -> None:
    module = _load_window()
    x11 = FakeX11()
    xext = FakeXext()
    result = module.set_empty_input_shape(4242, x11=x11, xext=xext)
    assert result is True
    assert xext.calls == [(77, 4242, 2, 0, 0, None, 0, 0, 0)]
    assert x11.calls == [
        ("XOpenDisplay", (None,)),
        ("XFlush", (77,)),
        ("XCloseDisplay", (77,)),
    ]


def test_should_return_false_and_not_close_when_no_display() -> None:
    module = _load_window()
    x11 = FakeX11(no_display=True)
    xext = FakeXext()
    result = module.set_empty_input_shape(4242, x11=x11, xext=xext)
    assert result is False
    assert xext.calls == []
    assert x11.calls == [("XOpenDisplay", (None,))]


def test_should_close_display_when_shape_call_raises() -> None:
    module = _load_window()
    x11 = FakeX11()
    xext = FakeXext(boom=True)
    with pytest.raises(RuntimeError):
        module.set_empty_input_shape(4242, x11=x11, xext=xext)
    assert x11.calls[-1] == ("XCloseDisplay", (77,))


def test_should_return_false_when_libraries_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_window()
    monkeypatch.setattr(module.ctypes.util, "find_library", lambda name: None)
    assert module.set_empty_input_shape(4242) is False
