"""The system controls: fixed argv lines per control, honest platform errors (FR-PC-06/07/13)."""

import shutil
from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest

from jarvis.system.controls import CommandResult, OsRunner, SystemControls, SystemError

_Usage = namedtuple("_Usage", ["total", "used", "free"])
_Proc = namedtuple("_Proc", ["stdout", "stderr", "returncode"])

WPCTL_STATUS = """
Sink \\#43: [AVOID] Built-in Audio Analog Stereo
Sinks:
\t* 45. Family Output
\t 47. Headphones
Sources:
\t* 46. Mic
"""


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


def test_should_lock_through_the_screensaver_bus(controls: Any) -> None:
    system, runner = controls
    assert system.lock() == {"locked": True}
    assert "org.gnome.ScreenSaver.Lock" in runner.argvs[-1]


def test_should_power_sleep_through_login1(controls: Any) -> None:
    system, runner = controls
    assert system.power("sleep") == {"power": "sleep"}
    assert "org.freedesktop.login1.manager.sleep" in [argv[-1].lower() for argv in runner.argvs]


def test_should_power_signout_through_the_session_manager(controls: Any) -> None:
    system, runner = controls
    system.power("signout")
    assert "org.gnome.sessionmanager.logout" in [argv[-2].lower() for argv in runner.argvs]


def test_should_refuse_an_unknown_power_action(controls: Any) -> None:
    with pytest.raises(SystemError):
        SystemControls(FakeRunner()).power("format")


def test_should_open_url_with_xdg_open(controls: Any) -> None:
    system, runner = controls
    assert system.open_url("https://example.com") == {"opened": "https://example.com"}
    assert _last(runner) == ["xdg-open", "https://example.com"]


def test_should_list_output_sinks_from_wpctl_status(controls: Any) -> None:
    system, runner = controls
    runner.stdout = WPCTL_STATUS
    listed = system.output_device(0)
    assert listed["devices"] == ["45. Family Output", "47. Headphones"]
    assert listed["active"] == 45


def test_should_switch_output_device_to_the_asked_sink(controls: Any) -> None:
    system, runner = controls
    runner.stdout = WPCTL_STATUS
    assert system.output_device(47) == {"set": "47. Headphones"}
    assert _last(runner) == ["wpctl", "set-default", "47"]


def test_should_not_find_an_output_device_that_was_not_listed(controls: Any) -> None:
    system, runner = controls
    runner.stdout = WPCTL_STATUS
    with pytest.raises(SystemError) as err:
        system.output_device(99)
    assert err.value.code == "NOT_FOUND" and "list them first" in err.value.message


def test_should_system_info_read_the_kernel_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    battery = tmp_path / "BAT0"
    battery.mkdir()
    (battery / "capacity").write_text("73\n", encoding="utf-8")
    monkeypatch.setattr("jarvis.system.controls._POWER_SUPPLY_DIR", tmp_path)
    meminfo = "MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n"
    monkeypatch.setattr(
        "jarvis.system.controls._read_file",
        lambda p: meminfo if "/proc/meminfo" in p else "1234.00 0.00",
    )
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: _Usage(100, 50, 50))
    info = SystemControls(FakeRunner()).info()
    assert info == {
        "battery": 73,
        "memory_used_percent": 50.0,
        "disk_used_percent": 50.0,
        "uptime_s": 1234,
    }


def test_should_fail_when_a_battery_level_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    battery = tmp_path / "BAT0"
    battery.mkdir()
    (battery / "capacity").write_text("brownout\n", encoding="utf-8")
    monkeypatch.setattr("jarvis.system.controls._POWER_SUPPLY_DIR", tmp_path)
    with pytest.raises(SystemError) as err:
        SystemControls(FakeRunner()).info()
    assert err.value.code == "INTERNAL"


def test_should_keep_hold_of_the_runner_when_the_os_runner_has_the_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wpctl")
    monkeypatch.setattr(
        "jarvis.system.controls.subprocess",
        _FakeSubprocess("Sinks:\n\t* 45. Speakers\n"),
    )
    listed = SystemControls(OsRunner()).output_device(0)
    assert listed["devices"] == ["45. Speakers"]


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


class _FakeSubprocess:
    """Stands in for the subprocess module; every run succeeds with a canned output."""

    def __init__(self, line: str) -> None:
        self._line = line

    def run(self, *_argv: list[str], **_kw: object) -> Any:
        return _Proc(self._line, "", 0)
