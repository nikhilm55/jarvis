"""Tests for fast-path window intents (FR-NLU-02)."""

import pytest

from jarvis.fastpath.intents import CloseApp, FocusWindow, WindowAction
from jarvis.fastpath.matcher import match

ACCEPTED_CASES: list[tuple[str, object]] = [
    ("switch to firefox", FocusWindow("firefox")),
    ("switch to the firefox", FocusWindow("firefox")),
    ("switch to firefox window", FocusWindow("firefox")),
    ("switch to the firefox window", FocusWindow("firefox")),
    ("focus firefox", FocusWindow("firefox")),
    ("focus on firefox", FocusWindow("firefox")),
    ("focus the firefox", FocusWindow("firefox")),
    ("focus the firefox window", FocusWindow("firefox")),
    ("bring firefox to the front", FocusWindow("firefox")),
    ("bring the firefox window to the front", FocusWindow("firefox")),
    ("bring up firefox", FocusWindow("firefox")),
    ("minimise firefox", WindowAction("firefox", "minimize")),
    ("minimize the firefox", WindowAction("firefox", "minimize")),
    ("minimise the firefox window", WindowAction("firefox", "minimize")),
    ("minimize firefox window", WindowAction("firefox", "minimize")),
    ("maximise firefox", WindowAction("firefox", "maximize")),
    ("maximize the firefox", WindowAction("firefox", "maximize")),
    ("maximise the firefox window", WindowAction("firefox", "maximize")),
    ("maximize firefox window", WindowAction("firefox", "maximize")),
    ("close the firefox window", WindowAction("firefox", "close")),
    ("close firefox window", WindowAction("firefox", "close")),
    ("can you please switch to firefox", FocusWindow("firefox")),
    ("switch to firefox please", FocusWindow("firefox")),
    ("can you please minimize the firefox window", WindowAction("firefox", "minimize")),
    ("maximize the firefox window please", WindowAction("firefox", "maximize")),
    ("close the firefox window please", WindowAction("firefox", "close")),
    ("switch to visual studio code", FocusWindow("visual studio code")),
    ("focus google chrome", FocusWindow("google chrome")),
    ("minimize the files window", WindowAction("files", "minimize")),
    ("maximise the calculator", WindowAction("calculator", "maximize")),
    ("close the google chrome window", WindowAction("google chrome", "close")),
    ("bring up visual studio code", FocusWindow("visual studio code")),
    ("focus on the google chrome window", FocusWindow("google chrome")),
    ("can you please close the firefox window", WindowAction("firefox", "close")),
]


REJECTED_CASES: list[str] = [
    "switch to this window",
    "switch to the next window",
    "switch to the previous window",
    "focus it",
    "minimize this",
    "minimize that window",
    "maximise it",
    "close this window",
    "close the other window",
    "close the window",
    "maximize the window",
    "minimize everything",
    "minimize all windows",
    "close all windows",
    "switch to dark mode",
    "switch to the second monitor",
    "switch to tab two",
    "switch to workspace 2",
    "minimize firefox and chrome",
    "switch to firefox and play music",
    "maximize firefox on the second monitor",
    "focus firefox then close it",
    "close the firefox window and open chrome",
    "switch to 2",
    "switch to a b c d e",
]


CLOSE_APP_CASES: list[tuple[str, object]] = [
    ("close firefox", CloseApp("firefox")),
    ("close the firefox", CloseApp("firefox")),
    ("open firefox window", None),
]


NORMALISATION_CASES: list[tuple[str, object]] = [
    ("Switch To  Visual Studio Code", FocusWindow("visual studio code")),
    ("FOCUS GOOGLE CHROME", FocusWindow("google chrome")),
    ("Minimise The Firefox Window", WindowAction("firefox", "minimize")),
    ("MAXIMIZE THE CALCULATOR", WindowAction("calculator", "maximize")),
    ("Close The Google Chrome Window", WindowAction("google chrome", "close")),
    ("Bring Up Visual Studio Code", FocusWindow("visual studio code")),
]


@pytest.mark.parametrize("command,expected", ACCEPTED_CASES)
def test_should_accept_window_intents(command: str, expected: object) -> None:
    assert match(command) == expected


@pytest.mark.parametrize("command", REJECTED_CASES)
def test_should_reject_non_window_commands(command: str) -> None:
    assert match(command) is None


@pytest.mark.parametrize("command,expected", CLOSE_APP_CASES)
def test_should_keep_close_app_behaviour(command: str, expected: object) -> None:
    assert match(command) == expected


@pytest.mark.parametrize("command,expected", NORMALISATION_CASES)
def test_should_normalise_window_names(command: str, expected: object) -> None:
    assert match(command) == expected
