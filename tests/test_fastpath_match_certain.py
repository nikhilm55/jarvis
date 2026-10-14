"""Tests for jarvis.fastpath.matcher: certain-only edge cases (FR-NLU-02)."""

import pytest

from jarvis.fastpath.intents import CloseApp, OpenApp, VolumeStep
from jarvis.fastpath.matcher import match

NOT_CERTAIN: list[str] = [
    # bare louder/quieter are Jarvis's speech volume (FRS Appendix C), not the system volume
    "louder",
    "quieter",
    "make it louder",
    "make it quieter",
    "Quieter please.",
    # symbols inside the target are never silently dropped
    "open Tom & Jerry",
    "open C/C++",
    "open firefox | calculator",
    "open $HOME",
    "open @home",
    "open (firefox)",
    "open a=b",
    "close firefox ^ calculator",
    "open ~/Downloads",
    # overloaded verbs followed by a determiner
    "run a backup",
    "run the backup",
    "start a backup",
    "start the calculator",
    "quit the text editor",
    "exit the terminal",
    "kill the process",
    "kill the firefox",
    # digits-only targets
    "open 5",
    "close 2024",
    "run 7",
    # time words after the target
    "open calculator now",
    "open firefox later",
    "open firefox tomorrow",
    "close calculator today",
    "open firefox tonight",
    "close terminal yesterday",
    # generic nouns
    "quit smoking",
    "exit full screen",
    "open strategy",
    "close the bill",
    "open bill",
    "run backup",
    "start music",
    "run update",
    # Jarvis itself
    "close jarvis",
    "quit Jarvis",
    "exit jarvis.",
    "kill jarvis",
    "open jarvis",
    "close Jarvis please",
]

STILL_CERTAIN: list[tuple[str, OpenApp | CloseApp | VolumeStep]] = [
    ("open the calculator", OpenApp("calculator")),
    ("open a terminal", OpenApp("terminal")),
    ("close the terminal", CloseApp("terminal")),
    ("can you close the calculator", CloseApp("calculator")),
    ("launch the files application", OpenApp("files")),
    ("open c++", OpenApp("c++")),
    ("open notepad++", OpenApp("notepad++")),
    ("open gnome-terminal.", OpenApp("gnome-terminal")),
    ("Open Firefox!", OpenApp("firefox")),
    ("open firefox, please.", OpenApp("firefox")),
    ("open “Firefox”", OpenApp("firefox")),
    ("quit spotify", CloseApp("spotify")),
    ("kill slack", CloseApp("slack")),
    ("run slack", OpenApp("slack")),
    ("start thunderbird", OpenApp("thunderbird")),
    ("volume up", VolumeStep(10)),
    ("volume down", VolumeStep(-10)),
    ("turn it up", VolumeStep(10)),
    ("turn it down", VolumeStep(-10)),
    ("turn the volume up", VolumeStep(10)),
    ("turn the volume down", VolumeStep(-10)),
    ("raise the volume", VolumeStep(10)),
    ("lower the volume", VolumeStep(-10)),
]


@pytest.mark.parametrize("command", NOT_CERTAIN, ids=NOT_CERTAIN)
def test_should_return_none_when_command_is_not_certain(command: str) -> None:
    assert match(command) is None


@pytest.mark.parametrize(
    ("command", "expected"),
    STILL_CERTAIN,
    ids=[cmd for cmd, _ in STILL_CERTAIN],
)
def test_should_still_match_when_command_is_plain(
    command: str,
    expected: OpenApp | CloseApp | VolumeStep,
) -> None:
    assert match(command) == expected
