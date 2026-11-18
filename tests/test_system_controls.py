"""The system controls: fixed argv lines per control, honest platform errors (FR-PC-06/07/13)."""

import shutil
from typing import Any

import pytest

from jarvis.system.controls import CommandResult, OsRunner, SystemControls, SystemError


class FakeRunner:
    """Records the argv of every backend command; answers with a canned result."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []
        self.stdout = ""

    def run(self, argv: list[str]) -> CommandResult:
        self.argvs.append(argv)
        return CommandResult(stdout=self.stdout, stderr="", exit=0)


@pytest.fixture()
def controls() -> tuple[SystemControls, FakeRunner]:
    runner = FakeRunner()
    return SystemControls(runner), runner


def _last(runner: FakeRunner) -> list[str]:
    return runner.argvs[-1]


def test_should_dnd_with_gsettings_when_on(controls: Any) -> None:
    system, runner = controls
    assert system.dnd(True) == {"dnd": True}
    assert _last(runner) == [
        "gsettings",
        "set",
        "org.gnome.desktop.notifications",
        "show-banners",
        "false",
    ]


def test_should_dnd_reenable_banners_when_off(controls: Any) -> None:
    system, runner = controls
    system.dnd(False)
    assert _last(runner) == [
        "gsettings",
        "set",
        "org.gnome.desktop.notifications",
        "show-banners",
        "true",
    ]


def test_should_dark_mode_prefer_dark_when_on(controls: Any) -> None:
    system, runner = controls
    system.dark_mode(True)
    assert "prefer-dark" in _last(runner)


def test_should_night_light_toggle(controls: Any) -> None:
    system, runner = controls
    system.night_light(True)
    system.night_light(False)
    assert runner.argvs[-2][-1] == "true" and runner.argvs[-1][-1] == "false"


def test_should_set_brightness_as_a_percent(controls: Any) -> None:
    system, runner = controls
    assert system.brightness(30) == {"brightness": 30}
    assert _last(runner) == ["brightnessctl", "s", "30%"]


def test_should_media_use_playerctl(controls: Any) -> None:
    system, runner = controls
    system.media("previous")
    assert _last(runner) == ["playerctl", "previous"]


def test_should_refuse_an_unknown_media_action(controls: Any) -> None:
    with pytest.raises(SystemError):
        SystemControls(FakeRunner()).media("rewind")


def test_should_wifi_and_bluetooth_use_nmcli(controls: Any) -> None:
    system, runner = controls
    system.wifi(False)
    system.bluetooth(True)
    assert ["nmcli", "radio", "wifi", "off"] in runner.argvs
    assert ["nmcli", "radio", "bluetooth", "on"] in runner.argvs


def test_should_refuse_when_the_backend_program_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(SystemError) as err:
        SystemControls(OsRunner()).brightness(50)
    assert err.value.code == "UNSUPPORTED_ON_PLATFORM"
    assert "install brightnessctl" in err.value.message


def test_should_report_a_failed_backend_as_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/brightnessctl")

    class Broken:
        stdout = ""
        stderr = "no backlight\n"
        returncode = 5

    monkeypatch.setattr("jarvis.system.controls.subprocess.run", lambda *_a, **_k: Broken())
    with pytest.raises(SystemError) as err:
        SystemControls(OsRunner()).brightness(50)
    assert err.value.code == "INTERNAL" and "no backlight" in err.value.message
