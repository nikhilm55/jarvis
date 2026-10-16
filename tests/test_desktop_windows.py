"""WindowManager.list / resolve / focus (FR-PC-02), against a fake X server and window manager."""

import pytest

from jarvis.desktop.windows import Rect, WindowManager, make_ref, parse_ref
from tests.x_fake import FakeX


def manager(fake: FakeX) -> WindowManager:
    return WindowManager(fake)


def test_should_list_frontmost_first() -> None:
    fake = FakeX()
    for wid, title in ((1, "Bottom"), (2, "Middle"), (3, "Top")):
        fake.add(wid, title)
    assert [v.title for v in manager(fake).list()] == ["Top", "Middle", "Bottom"]


@pytest.mark.parametrize("kind", ["DOCK", "DESKTOP", "SPLASH", "NOTIFICATION", "TOOLTIP", "MENU"])
def test_should_leave_out_a_window_of_a_kind_the_user_does_not_see_as_a_window(kind: str) -> None:
    fake = FakeX()
    fake.add(1, "Real")
    fake.add(2, "Hidden kind", types=[kind])
    fake.add(3, "Dialog", types=["DIALOG"])
    assert [v.title for v in manager(fake).list()] == ["Dialog", "Real"]


def test_should_report_each_state_and_combine_them_in_order() -> None:
    fake = FakeX()
    fake.add(1, "Plain")
    fake.add(2, "Away", states=["HIDDEN"])
    fake.add(3, "Half", states=["MAXIMIZED_VERT"])  # one flag is not maximised
    fake.add(4, "Big", states=["MAXIMIZED_VERT", "MAXIMIZED_HORZ"])
    fake.add(5, "Front", states=["MAXIMIZED_VERT", "MAXIMIZED_HORZ"])
    fake.add(6, "Gone", states=["HIDDEN", "MAXIMIZED_VERT", "MAXIMIZED_HORZ"])
    fake.active = 5
    states = {v.title: v.state for v in manager(fake).list()}
    assert states == {
        "Plain": ("normal",),
        "Away": ("minimized",),
        "Half": ("normal",),
        "Big": ("maximized",),
        "Front": ("maximized", "focused"),
        "Gone": ("minimized", "maximized"),
    }


def test_should_put_a_window_on_the_monitor_that_holds_its_centre() -> None:
    fake = FakeX(monitors=[Rect(0, 0, 1000, 1000), Rect(1000, 0, 1000, 1000)])
    fake.add(1, "Left", rect=Rect(100, 100, 200, 200))
    fake.add(2, "Right", rect=Rect(1100, 100, 200, 200))
    fake.add(3, "Straddles", rect=Rect(900, 100, 400, 200))  # centre x = 1100
    fake.add(4, "Nowhere", rect=Rect(-500, -500, 100, 100))
    monitors = {v.title: v.monitor for v in manager(fake).list()}
    assert monitors == {"Left": 0, "Right": 1, "Straddles": 1, "Nowhere": 0}


def test_should_give_each_window_a_stable_ref_and_its_title_and_class() -> None:
    fake = FakeX()
    fake.add(0x1234, "My Title", app="myapp")
    (view,) = manager(fake).list()
    assert (view.ref, view.title, view.wm_instance, view.wm_class) == (
        "x11:0x1234",
        "My Title",
        "myapp",
        "Myapp",
    )
    assert parse_ref(view.ref) == 0x1234
    assert make_ref(0x1234) == view.ref


@pytest.mark.parametrize("text", ["firefox", "x11:1234", "x11:0xzz", "x11:0x", "X11:0x1g", ""])
def test_should_not_take_other_text_for_a_ref(text: str) -> None:
    assert parse_ref(text) is None
