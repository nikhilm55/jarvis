"""WindowManager.list / resolve / focus (FR-PC-02), against a fake X server and window manager."""

from collections.abc import Callable

import pytest

from jarvis.desktop.windows import (
    WINDOW_OPS,
    Rect,
    WindowError,
    WindowManager,
    make_ref,
    parse_ref,
)
from tests.x_fake import FakeX


class Clock:
    """Fake time: `sleep` advances `now` and runs hooks (to make an effect arrive late)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps = 0
        self.on_sleep: list[Callable[[int], None]] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.sleeps += 1
        for hook in list(self.on_sleep):
            hook(self.sleeps)


def manager(fake: FakeX, clock: Clock | None = None) -> WindowManager:
    clock = clock or Clock()
    return WindowManager(fake, sleep=clock.sleep, now=clock.now)


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


def test_should_resolve_a_ref_only_if_the_window_is_listed() -> None:
    fake = FakeX()
    fake.add(0x100, "Listed")
    fake.add(0x200, "A panel", types=["DOCK"])
    wm = manager(fake)
    assert wm.resolve("x11:0x100") == 0x100
    assert wm.resolve(" X11:0x100 ") == 0x100
    with pytest.raises(WindowError) as info:
        wm.resolve("x11:0x200")
    assert info.value.code == "NOT_FOUND"
    assert info.value.alternatives == ()  # nothing is close to a bare ref
    with pytest.raises(WindowError) as gone:
        wm.resolve("x11:0x999")
    assert gone.value.code == "NOT_FOUND"


def test_should_prefer_an_exact_match_to_a_prefix_to_a_substring() -> None:
    fake = FakeX()
    fake.add(1, "My Calculator Suite", app="suite")  # substring
    fake.add(2, "Calculator Tools", app="tools")  # prefix
    fake.add(3, "Calculator", app="calc")  # exact
    wm = manager(fake)
    assert wm.resolve("calculator") == 3
    fake.windows.pop(3)
    assert wm.resolve("calculator") == 2
    fake.windows.pop(2)
    assert wm.resolve("calculator") == 1


def test_should_match_the_window_class_and_ignore_case_and_padding() -> None:
    fake = FakeX()
    fake.add(1, "Untitled - 3", app="gnome-calculator")
    fake.add(2, "Other", app="other")
    wm = manager(fake)
    assert wm.resolve("gnome-calculator") == 1  # the instance
    assert wm.resolve("Gnome-calculator") == 1  # the class is title-cased by the fake
    assert wm.resolve("  GNOME-CALCULATOR ") == 1


def test_should_take_the_frontmost_when_the_best_matches_are_windows_of_one_app() -> None:
    fake = FakeX()
    fake.add(1, "Terminal", app="term")
    fake.add(2, "Terminal", app="term")
    assert manager(fake).resolve("terminal") == 2  # added last = on top


def test_should_refuse_to_guess_between_apps_and_name_the_titles() -> None:
    fake = FakeX()
    fake.add(1, "Terminal", app="term1")
    fake.add(2, "Terminal Two", app="term2")
    fake.add(3, "Terminal", app="term3")
    with pytest.raises(WindowError) as info:
        manager(fake).resolve("terminal")
    assert info.value.code == "AMBIGUOUS"
    assert "Terminal" in info.value.message


def test_should_answer_not_found_with_the_closest_titles() -> None:
    fake = FakeX()
    for wid, title in enumerate(("Calculator", "Editor", "Browser", "Calendar", "Mail"), 1):
        fake.add(wid, title)
    with pytest.raises(WindowError) as info:
        manager(fake).resolve("Calculater")
    assert info.value.code == "NOT_FOUND"
    assert info.value.alternatives[0] == "Calculator"
    assert len(info.value.alternatives) <= 5
    assert "Calculater" in info.value.message


def test_should_offer_a_looser_near_miss_and_at_most_five() -> None:
    fake = FakeX()
    fake.add(1, "Calculator")
    for wid in range(2, 10):
        fake.add(wid, f"Note {wid}")
    with pytest.raises(WindowError) as near:
        manager(fake).resolve("Calcx")
    assert near.value.alternatives == ("Calculator",)  # a loose match still counts
    with pytest.raises(WindowError) as many:
        manager(fake).resolve("Notes x")
    assert len(many.value.alternatives) == 5


def test_should_answer_not_found_without_alternatives_when_nothing_is_close() -> None:
    fake = FakeX()
    fake.add(1, "Calculator")
    with pytest.raises(WindowError) as info:
        manager(fake).resolve("zzzzzz")
    assert (info.value.code, info.value.alternatives) == ("NOT_FOUND", ())


@pytest.mark.parametrize("text", ["", "   "])
def test_should_not_resolve_blank_text(text: str) -> None:
    fake = FakeX()
    fake.add(1, "Anything")
    with pytest.raises(WindowError) as info:
        manager(fake).resolve(text)
    assert info.value.code == "INVALID_ARGUMENT"


def test_should_focus_with_the_pager_message_and_say_the_window_is_focused() -> None:
    fake = FakeX()
    fake.add(1, "Target")
    fake.add(2, "Other")
    fake.active = 2
    view = manager(fake).focus("target")
    assert fake.sent == [(1, "_NET_ACTIVE_WINDOW", (2, 4242, 2, 0, 0))]
    assert fake.active == 1
    assert "focused" in view.state
    assert fake.stacking()[-1] == 1  # in front


def test_should_restore_a_minimised_window_before_focusing_it() -> None:
    fake = FakeX()
    fake.add(1, "Away", states=["HIDDEN"])
    view = manager(fake).focus("x11:0x1")
    assert "HIDDEN" not in fake.windows[1].states
    assert fake.active == 1
    assert view.state == ("focused",)
    assert [m for _, m, _ in fake.sent] == ["_NET_ACTIVE_WINDOW", "_NET_ACTIVE_WINDOW"]


def test_should_fail_to_focus_when_the_window_manager_ignores_the_request() -> None:
    fake = FakeX()
    fake.add(1, "Stubborn")
    fake.responsive = False
    clock = Clock()
    with pytest.raises(WindowError) as info:
        manager(fake, clock).focus("stubborn")
    assert info.value.code == "ACTION_FAILED"
    assert "did not take focus" in info.value.message
    assert "ask again" in info.value.message  # the remedy
    assert clock.t == pytest.approx(1.0, abs=0.06)  # it waited its second, no more


def test_should_fail_to_restore_when_the_window_stays_minimised() -> None:
    fake = FakeX()
    fake.add(1, "Away", states=["HIDDEN"])
    fake.responsive = False
    with pytest.raises(WindowError) as info:
        manager(fake).focus("away")
    assert info.value.code == "ACTION_FAILED"
    assert "minimised" in info.value.message


def test_should_wait_for_a_window_manager_that_is_slow_to_answer() -> None:
    fake = FakeX()
    fake.add(1, "Slow")
    fake.responsive = False
    clock = Clock()

    def answer_on_third_poll(sleeps: int) -> None:
        if sleeps == 3:
            fake.active = 1

    clock.on_sleep.append(answer_on_third_poll)
    view = manager(fake, clock).focus("slow")
    assert "focused" in view.state
    assert clock.sleeps == 3


def test_should_not_send_anything_when_the_window_is_unknown() -> None:
    fake = FakeX()
    fake.add(1, "Here")
    with pytest.raises(WindowError):
        manager(fake).focus("nowhere")
    assert fake.sent == []


MAX = ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")


def sent_messages(fake: FakeX) -> list[str]:
    return [message for _, message, _ in fake.sent]


def test_should_minimise_with_the_iconic_state_message_and_say_so() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    (view,) = manager(fake).window_op("calc", "minimize")
    assert fake.sent == [(1, "WM_CHANGE_STATE", (3,))]
    assert "HIDDEN" in fake.windows[1].states
    assert view.state == ("minimized",)


def test_should_send_nothing_to_minimise_a_window_that_is_already_minimised() -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=["HIDDEN"])
    manager(fake).window_op("calc", "minimize")
    assert fake.sent == []


def test_should_maximise_with_the_exact_state_message() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    (view,) = manager(fake).window_op("calc", "maximize")
    assert fake.sent == [(1, "_NET_WM_STATE", (1, *MAX, 2, 0))]
    assert view.state == ("maximized",)


def test_should_restore_a_minimised_window_before_maximising_it() -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=["HIDDEN"])
    (view,) = manager(fake).window_op("calc", "maximize")
    assert sent_messages(fake) == ["_NET_ACTIVE_WINDOW", "_NET_WM_STATE"]
    assert view.state == ("maximized", "focused")


def test_should_send_nothing_to_maximise_a_window_that_is_already_maximised() -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=["MAXIMIZED_VERT", "MAXIMIZED_HORZ"])
    manager(fake).window_op("calc", "maximize")
    assert fake.sent == []


def test_should_restore_a_maximised_window_by_removing_both_flags() -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=["MAXIMIZED_VERT", "MAXIMIZED_HORZ"])
    (view,) = manager(fake).window_op("calc", "restore")
    assert fake.sent == [(1, "_NET_WM_STATE", (0, *MAX, 2, 0))]
    assert view.state == ("normal",)


def test_should_restore_a_minimised_window_by_activating_it() -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=["HIDDEN"])
    manager(fake).window_op("calc", "restore")
    assert fake.sent == [(1, "_NET_ACTIVE_WINDOW", (2, 4242, 0, 0, 0))]
    assert "HIDDEN" not in fake.windows[1].states


def test_should_send_nothing_to_restore_a_window_that_is_normal() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    manager(fake).window_op("calc", "restore")
    assert fake.sent == []


def test_should_close_with_the_exact_message_and_report_the_window_as_it_was() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    fake.active = 1
    (view,) = manager(fake).window_op("calc", "close")
    assert fake.sent == [(1, "_NET_CLOSE_WINDOW", (4242, 2, 0, 0, 0))]
    assert 1 not in fake.windows
    assert (view.title, view.state) == ("Calc", ("focused",))


@pytest.mark.parametrize(
    ("op", "states", "word"),
    [
        ("minimize", [], "stayed visible"),
        ("maximize", [], "did not fill"),
        ("restore", ["MAXIMIZED_VERT", "MAXIMIZED_HORZ"], "stayed maximised"),
        ("close", [], "still open"),
    ],
)
def test_should_fail_an_op_the_window_manager_ignores_and_name_the_op(
    op: str, states: list[str], word: str
) -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=states)
    fake.responsive = False
    clock = Clock()
    with pytest.raises(WindowError) as info:
        manager(fake, clock).window_op("calc", op)
    assert info.value.code == "ACTION_FAILED"
    assert info.value.message.startswith(f"{op} did not work")
    assert word in info.value.message
    assert clock.t == pytest.approx(1.0, abs=0.06)


def test_should_say_a_close_may_be_waiting_for_a_save() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    fake.responsive = False
    with pytest.raises(WindowError) as info:
        manager(fake).window_op("calc", "close")
    assert "asking to save" in info.value.message


def test_should_fail_to_maximise_a_window_that_cannot_be_restored_first() -> None:
    fake = FakeX()
    fake.add(1, "Calc", states=["HIDDEN"])
    fake.responsive = False
    with pytest.raises(WindowError) as info:
        manager(fake).window_op("calc", "maximize")
    assert "stayed minimised" in info.value.message


@pytest.mark.parametrize("op", ["explode", "", "MINIMIZE", "minimise"])
def test_should_refuse_an_unknown_op_and_list_the_valid_ones(op: str) -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    with pytest.raises(WindowError) as info:
        manager(fake).window_op("calc", op)
    assert info.value.code == "INVALID_ARGUMENT"
    for valid in WINDOW_OPS:
        assert valid in info.value.message
    assert fake.sent == []


def test_should_not_send_anything_for_an_op_on_an_unknown_window() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    with pytest.raises(WindowError) as info:
        manager(fake).window_op("nothing here", "close")
    assert info.value.code == "NOT_FOUND"
    assert fake.sent == []


def test_should_wait_for_an_op_whose_effect_arrives_late() -> None:
    fake = FakeX()
    fake.add(1, "Calc")
    fake.responsive = False
    clock = Clock()

    def minimise_on_third_poll(sleeps: int) -> None:
        if sleeps == 3:
            fake.windows[1].states.add("HIDDEN")

    clock.on_sleep.append(minimise_on_third_poll)
    manager(fake, clock).window_op("calc", "minimize")
    assert clock.sleeps == 3
