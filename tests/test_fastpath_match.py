import itertools
import time

import pytest

from jarvis.fastpath.intents import (
    CloseApp,
    Intent,
    Mute,
    OpenApp,
    Stop,
    TellDate,
    TellTime,
    VolumeSet,
    VolumeStep,
)
from jarvis.fastpath.matcher import match

ACCEPTED: list[tuple[str, Intent]] = [
    ("open calculator", OpenApp("calculator")),
    ("Open Firefox.", OpenApp("firefox")),
    ("OPEN TERMINAL", OpenApp("terminal")),
    ("launch spotify", OpenApp("spotify")),
    ("start thunderbird", OpenApp("thunderbird")),
    ("run slack", OpenApp("slack")),
    ("open the calculator", OpenApp("calculator")),
    ("open up firefox", OpenApp("firefox")),
    ("open a terminal", OpenApp("terminal")),
    ("open vs code", OpenApp("vs code")),
    ("Open Visual Studio Code!", OpenApp("visual studio code")),
    ("open text editor", OpenApp("text editor")),
    ("open files", OpenApp("files")),
    ("please open calculator", OpenApp("calculator")),
    ("can you open firefox", OpenApp("firefox")),
    ("could you please open the terminal", OpenApp("terminal")),
    ("open firefox please", OpenApp("firefox")),
    ("Open Firefox. Thanks.", OpenApp("firefox")),
    ("open calculator app", OpenApp("calculator")),
    ("launch the files application", OpenApp("files")),
    ("open gnome-terminal", OpenApp("gnome-terminal")),
    ("open notepad++", OpenApp("notepad++")),
    ("open google chrome", OpenApp("google chrome")),
    ("open \u201cFirefox\u201d", OpenApp("firefox")),
    ("open caf\u00e9", OpenApp("caf\u00e9")),
    ("close calculator", CloseApp("calculator")),
    ("Close Firefox.", CloseApp("firefox")),
    ("quit spotify", CloseApp("spotify")),
    ("exit terminal", CloseApp("terminal")),
    ("kill slack", CloseApp("slack")),
    ("close the terminal", CloseApp("terminal")),
    ("close vs code please", CloseApp("vs code")),
    ("quit the text editor", CloseApp("text editor")),
    ("close firefox, thanks", CloseApp("firefox")),
    ("can you close the calculator", CloseApp("calculator")),
    ("what time is it", TellTime()),
    ("What time is it?", TellTime()),
    ("what's the time", TellTime()),
    ("what is the time", TellTime()),
    ("time?", TellTime()),
    ("tell me the time", TellTime()),
    ("what's the time right now", TellTime()),
    ("what time is it now", TellTime()),
    ("current time", TellTime()),
    ("what's the date", TellDate()),
    ("What's today's date?", TellDate()),
    ("what is the date today", TellDate()),
    ("what day is it", TellDate()),
    ("what day is it today", TellDate()),
    ("today's date", TellDate()),
    ("tell me the date", TellDate()),
    ("what day is today", TellDate()),
    ("volume up", VolumeStep(10)),
    ("volume down", VolumeStep(-10)),
    ("Volume up.", VolumeStep(10)),
    ("turn it up", VolumeStep(10)),
    ("turn it down", VolumeStep(-10)),
    ("turn the volume up", VolumeStep(10)),
    ("turn volume down", VolumeStep(-10)),
    ("turn up the volume", VolumeStep(10)),
    ("turn down the volume", VolumeStep(-10)),
    ("raise the volume", VolumeStep(10)),
    ("lower the volume", VolumeStep(-10)),
    ("decrease the volume", VolumeStep(-10)),
    ("reduce the volume", VolumeStep(-10)),
    ("increase the volume", VolumeStep(10)),
    ("louder", VolumeStep(10)),
    ("quieter", VolumeStep(-10)),
    ("make it louder", VolumeStep(10)),
    ("set volume to 40", VolumeSet(40)),
    ("set the volume to 40 percent", VolumeSet(40)),
    ("volume 40 percent", VolumeSet(40)),
    ("Volume 40%.", VolumeSet(40)),
    ("volume 100", VolumeSet(100)),
    ("set volume to 0", VolumeSet(0)),
    ("volume to 25", VolumeSet(25)),
    ("change the volume to 75 percent please", VolumeSet(75)),
    ("put the volume at 30", VolumeSet(30)),
    ("mute", Mute(True)),
    ("Mute.", Mute(True)),
    ("unmute", Mute(False)),
    ("Unmute!", Mute(False)),
    ("mute the sound", Mute(True)),
    ("unmute the sound", Mute(False)),
    ("mute audio", Mute(True)),
    ("un-mute", Mute(False)),
    ("stop", Stop()),
    ("Stop.", Stop()),
    ("cancel", Stop()),
    ("shut up", Stop()),
    ("never mind", Stop()),
    ("Never mind.", Stop()),
    ("nevermind", Stop()),
    ("stop please", Stop()),
]

REJECTED: list[str] = [
    "",
    "   ",
    "...",
    "please",
    "open",
    "close",
    "open it",
    "close it",
    "open that",
    "open the app",
    "open my calculator",
    "open john's firefox",
    "open calculator and type 5",
    "open firefox and search for news",
    "open terminal then run ls",
    "open firefox, calculator",
    "open firefox and calculator",
    "close all windows except firefox",
    "close everything",
    "open the file I downloaded yesterday",
    "open my chat with John",
    "open calculator for me",
    "close calculator and save work",
    "open firefox.com",
    "open https://example.com",
    "start recording",
    "start the timer",
    "run ls -la",
    "Open Firefox. Close Calculator.",
    "open firefox, then",
    "open " + "a" * 200,
    "what time is it in Tokyo",
    "what is the time zone",
    "what day is the meeting",
    "volume up and play music",
    "turn it up and play",
    "set volume to 150",
    "set volume to -10",
    "set volume to 40.5",
    "set volume to forty",
    "turn up the heat",
    "turn it on",
    "mute the microphone",
    "mute yourself",
    "stop it",
    "stop playing music",
    "stop and open firefox",
    "cancel my meeting",
    "stop the timer",
    "close this window",
    "never mind open firefox",
    "hello there",
    "open \u0938\u0902\u0917\u0940\u0924",
]


@pytest.mark.parametrize("command,expected", ACCEPTED, ids=[c for c, _ in ACCEPTED])
def test_should_match_intent_when_command_is_unambiguous(command: str, expected: Intent) -> None:
    assert match(command) == expected


@pytest.mark.parametrize("command", REJECTED, ids=[repr(c) for c in REJECTED])
def test_should_return_none_when_command_is_not_certain(command: str) -> None:
    assert match(command) is None


def test_should_have_enough_cases() -> None:
    assert len(ACCEPTED) >= 40
    assert len(REJECTED) >= 15


def test_should_average_under_one_millisecond_when_matching_a_thousand_commands() -> None:
    commands = list(itertools.islice(itertools.cycle([c for c, _ in ACCEPTED] + REJECTED), 1000))
    start = time.perf_counter()
    for command in commands:
        match(command)
    elapsed = time.perf_counter() - start
    assert elapsed / 1000 < 0.001
