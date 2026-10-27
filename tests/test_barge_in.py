"""Barge-in (R88, FR-ACT-09): through an echo-cancelled mic, only a stop word acts over Jarvis."""

import asyncio
import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

from jarvis import cli
from jarvis.audio import MicSource
from jarvis.audio import sources as audio_sources
from jarvis.audio.echo import ENABLE_HINT, echo_cancel_source
from jarvis.orchestrator.listener import is_stop_phrase
from tests.listener_rig import make_listener_rig, seg

LISTING = (
    "55\talsa_output.pci.HiFi__sink.monitor\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
    "59\talsa_input.pci.HiFi__source\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("70\techo-cancel-source\tPipeWire\tfloat32le 1ch 48000Hz\tIDLE\n", "echo-cancel-source"),
        ("71\tEcho_Cancel_Mic\tPipeWire\tfloat32le 1ch 48000Hz\tIDLE\n", "Echo_Cancel_Mic"),
        ("72\techo-cancel-sink.monitor\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n", None),
        ("", None),
    ],
)
def test_should_find_the_echo_cancelled_source_and_never_a_monitor(
    extra: str, expected: str | None
) -> None:
    assert echo_cancel_source(run=lambda argv: LISTING + extra) == expected


def test_should_find_none_when_pactl_fails() -> None:
    def broken(argv: list[str]) -> str:
        raise subprocess.CalledProcessError(1, argv)

    assert echo_cancel_source(run=broken) is None


@pytest.mark.parametrize(
    ("text", "stops"),
    [
        ("stop", True),
        ("Stop.", True),
        ("Jarvis, stop", True),
        ("Hey Jarvis, cancel", True),
        ("quiet please", True),
        ("stop the music", False),  # a command, not the gate word
        ("I'll stop the timer for you.", False),  # Jarvis's own words echoing back
        ("open calculator", False),
        ("", False),
    ],
)
def test_should_take_only_a_bare_stop_word(text: str, stops: bool) -> None:
    assert is_stop_phrase(text) is stops


def _overlapping(tmp_path: Path, text: str, *, barge_in: bool) -> Any:
    rig = make_listener_rig(tmp_path, [text])
    rig.listener._s = dataclasses.replace(rig.listener._s, barge_in=barge_in)
    asyncio.run(rig.listener.handle(seg(tainted=True)))
    return rig


def test_should_stop_jarvis_when_told_to_over_its_voice(tmp_path: Path) -> None:
    rig = _overlapping(tmp_path, "Jarvis, stop", barge_in=True)
    assert rig.stops == 1 and rig.submitted == []


def test_should_never_start_a_turn_from_speech_over_jarvis(tmp_path: Path) -> None:
    rig = _overlapping(tmp_path, "Jarvis, open calculator", barge_in=True)
    assert rig.stops == 0 and rig.submitted == [] and rig.speaker.said == []


def test_should_ignore_speech_over_jarvis_without_echo_cancel(tmp_path: Path) -> None:
    rig = _overlapping(tmp_path, "Jarvis, stop", barge_in=False)
    assert rig.stops == 0 and rig.transcriber.texts == ["Jarvis, stop"]  # never transcribed


def test_should_stay_quiet_when_a_barge_in_transcription_fails(tmp_path: Path) -> None:
    rig = _overlapping(tmp_path, RuntimeError("stt down"), barge_in=True)  # type: ignore[arg-type]
    assert rig.stops == 0 and rig.speaker.said == []  # no "speech recognition" line over Jarvis


# --- capture through the echo-cancelled source ---------------------------------------------------


class FakeStream:
    opened: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        FakeStream.opened.append({**kwargs, "PULSE_SOURCE": os.environ.get("PULSE_SOURCE")})

    def start(self) -> None:
        raise RuntimeError("stop here")  # opening is all this test needs

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("device", "capture_from", "expected", "cancelled"),
    [
        (None, "echo-cancel-source", ("pulse", "echo-cancel-source"), True),
        ("3", "echo-cancel-source", (3, None), False),  # an explicit device wins
        (None, None, (None, None), False),
    ],
)
def test_should_open_the_echo_cancelled_source_through_pulse(
    monkeypatch: pytest.MonkeyPatch,
    device: str | None,
    capture_from: str | None,
    expected: tuple[object, str | None],
    cancelled: bool,
) -> None:
    fake = type(sys)("sounddevice")
    fake.InputStream = FakeStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.delenv("PULSE_SOURCE", raising=False)
    FakeStream.opened = []
    mic = MicSource(device, capture_from=capture_from)
    with pytest.raises(audio_sources.AudioDeviceError):
        next(iter(mic.frames()))
    [opened] = FakeStream.opened
    assert (opened["device"], opened["PULSE_SOURCE"]) == expected
    assert mic.echo_cancelled is cancelled


# --- jarvis doctor -------------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "line"), [(None, ENABLE_HINT), ("ec", "on, through")])
def test_should_say_whether_barge_in_works_and_how_to_turn_it_on(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str | None,
    line: str,
) -> None:
    monkeypatch.setattr(cli, "echo_cancel_source", lambda: source)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert line in out and "kill switch:" in out
