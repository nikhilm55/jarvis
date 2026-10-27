"""The fast path's window intents run through gated_dispatch and say what happened."""

import pytest

from jarvis.contract import validate_response
from jarvis.desktop.client import DesktopError
from jarvis.fastpath import FastPathDeclined
from jarvis.fastpath.intents import FocusWindow, Intent, WindowAction
from tests.fastpath_fakes import FakeDesktop, error_of, run


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.mark.parametrize(
    ("intent", "method", "args", "spoken", "tool", "undoable"),
    [
        (
            FocusWindow("calculator"),
            "focus_window",
            ("calculator",),
            "Calculator is in front.",
            "desktop.focus_window",
            False,
        ),
        (
            WindowAction("calculator", "minimize"),
            "window_op",
            ("calculator", "minimize"),
            "Minimised Calculator.",
            "desktop.window_op",
            False,
        ),
        (
            WindowAction("calculator", "maximize"),
            "window_op",
            ("calculator", "maximize"),
            "Maximised Calculator.",
            "desktop.window_op",
            False,
        ),
        (
            WindowAction("calculator", "close"),
            "window_op",
            ("calculator", "close"),
            "Closed the Calculator window.",
            "desktop.window_op",
            True,  # closing is undone by reopening the app (R90)
        ),
    ],
)
def test_should_run_the_window_intent_and_say_what_it_did(
    events: list[str],
    *,
    intent: Intent,
    method: str,
    args: tuple[str, ...],
    spoken: str,
    tool: str,
    undoable: bool,
) -> None:
    desktop = FakeDesktop(events)
    response = run(intent, desktop, "balanced")
    assert response.status == "success"
    assert response.spoken == spoken
    assert desktop.calls == [(method, args)]
    (action,) = response.actions_taken
    assert (action.tool, action.undoable) == (tool, undoable)
    assert validate_response(response.model_dump()).spoken == spoken


@pytest.mark.parametrize("intent", [FocusWindow("calculator"), WindowAction("calculator", "close")])
def test_should_not_touch_a_window_in_safe_mode_without_a_confirmation(
    events: list[str], intent: Intent
) -> None:
    desktop = FakeDesktop(events)
    response = run(intent, desktop, "safe")
    assert response.status == "failed"
    assert error_of(response).code == "BLOCKED_BY_POLICY"
    assert events == []


@pytest.mark.parametrize("code", ["NOT_FOUND", "AMBIGUOUS"])
@pytest.mark.parametrize("intent", [FocusWindow("settings"), WindowAction("settings", "maximize")])
def test_should_hand_an_unknown_or_unclear_window_to_the_brain(
    events: list[str], code: str, intent: Intent
) -> None:
    desktop = FakeDesktop(events, error=DesktopError(code, "msg"))
    with pytest.raises(FastPathDeclined) as exc:
        run(intent, desktop, "balanced")
    assert code in str(exc.value)


@pytest.mark.parametrize(
    ("intent", "action"),
    [
        (FocusWindow("calculator"), "switch to calculator"),
        (WindowAction("calculator", "minimize"), "minimise calculator"),
        (WindowAction("calculator", "maximize"), "maximise calculator"),
        (WindowAction("calculator", "close"), "close the calculator window"),
    ],
)
def test_should_say_what_it_could_not_do_when_the_window_did_not_obey(
    events: list[str], intent: Intent, action: str
) -> None:
    desktop = FakeDesktop(events, error=DesktopError("ACTION_FAILED", "it did not take focus"))
    response = run(intent, desktop, "balanced")
    assert response.status == "failed"
    assert response.spoken.startswith(f"I couldn't {action}.")
    assert error_of(response).why == "it did not take focus"
    assert error_of(response).code == "INTERNAL"  # ACTION_FAILED is not in Appendix B (OQ)
    assert error_of(response).remedy
    assert validate_response(response.model_dump()).spoken == response.spoken


def test_should_fall_back_to_the_spoken_name_when_the_result_names_no_app(
    events: list[str],
) -> None:
    desktop = FakeDesktop(events, results={"focus_window": {}, "window_op": {"windows": []}})
    assert run(FocusWindow("zoom"), desktop, "balanced").spoken == "zoom is in front."
    maximise = run(WindowAction("zoom", "maximize"), desktop, "balanced")
    assert maximise.spoken == "Maximised zoom."
