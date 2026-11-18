"""System controls run one fixed OS command each (FR-PC-06/07/13, plan task t11).

No control runs user text through a shell: every call is a fixed argv list built
from validated arguments, so there is nothing for the gate's shell classifier to
second-guess. A missing backend program is `UNSUPPORTED_ON_PLATFORM` with the
install hint (Appendix B), never a silent failure.

Controls (on Linux, per plan B): output device and mute come from wpctl (mute already
exists as desktop.mute), DND / dark mode / night light from gsettings, brightness from
brightnessctl, media keys from playerctl, Wi-Fi / Bluetooth from nmcli, lock from the
GNOME screensaver bus, and sleep / sign-out / restart / shutdown from login1. open_url
opens in the owner's browser (T1, R83 provenance on the URL). system_info reads the
kernel's own files — no commands at all.
"""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

__all__ = ["CommandResult", "Runner", "SystemControls", "SystemError"]

# Long enough for a login1/GNOME D-Bus round trip on a cold session, short enough
# that a stuck backend cannot hold a turn.
_TIMEOUT_S = 10


_INSTALL_HINTS = {
    "wpctl": "install PipeWire (the sound and output control comes with it)",
    "gsettings": "install GNOME's settings daemon",
    "brightnessctl": "install brightnessctl",
    "playerctl": "install playerctl",
    "nmcli": "install NetworkManager's client",
    "gdbus": "install GLib's gdbus (it comes with GNOME)",
    "xdg-open": "install xdg-utils",
}


class SystemError(Exception):
    """A control that cannot be done; `code` is an Appendix B code."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code and message."""
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CommandResult:
    """What one backend command produced."""

    stdout: str
    stderr: str
    exit: int


class Runner(Protocol):
    """One fixed argv list, run and waited for."""

    def run(self, argv: list[str]) -> CommandResult: ...


class OsRunner:
    """Run backend commands; missing programs fail loudly with an install hint."""

    def run(self, argv: list[str]) -> CommandResult:
        """Run one backend command; an uninstalled program is UNSUPPORTED_ON_PLATFORM."""
        program = argv[0]
        if shutil.which(program) is None:
            hint = _INSTALL_HINTS.get(program, "install it with your package manager")
            raise SystemError("UNSUPPORTED_ON_PLATFORM", f"{program} is not installed — {hint}")
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user text
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise SystemError(
                "INTERNAL", f"{program} did not finish within {_TIMEOUT_S} s"
            ) from None
        if done.returncode != 0:
            text = (done.stderr or done.stdout).strip().splitlines()
            detail = text[-1] if text else "no output"
            raise SystemError("INTERNAL", f"{program} failed: {detail}")
        return CommandResult(stdout=done.stdout, stderr=done.stderr, exit=0)


_MEDIA_ACTIONS = ("play", "pause", "toggle", "next", "previous")


class SystemControls:
    """One validated argument set per control; the command lines are fixed."""

    def __init__(self, runner: Runner) -> None:
        """Take a backend runner (the OS runner, or a fake in tests)."""
        self._runner = runner

    def dnd(self, on: bool) -> dict[str, object]:
        """Do not disturb: GNOME stops showing notification banners."""
        self._runner.run(
            [
                "gsettings",
                "set",
                "org.gnome.desktop.notifications",
                "show-banners",
                "false" if on else "true",
            ]
        )
        return {"dnd": on}

    def dark_mode(self, on: bool) -> dict[str, object]:
        """Switch GNOME between dark and light style."""
        scheme = "prefer-dark" if on else "default"
        self._runner.run(
            ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", scheme]
        )
        return {"dark_mode": on}

    def night_light(self, on: bool) -> dict[str, object]:
        """Turn GNOME's night light (the warm screen) on or off."""
        self._runner.run(
            [
                "gsettings",
                "set",
                "org.gnome.settings-daemon.plugins.color",
                "night-light-enabled",
                "true" if on else "false",
            ]
        )
        return {"night_light": on}

    def brightness(self, level: int) -> dict[str, object]:
        """Set the screen brightness as a percentage (1-100)."""
        self._runner.run(["brightnessctl", "s", f"{level}%"])
        return {"brightness": level}

    def media(self, action: str) -> dict[str, object]:
        """Drive the playing media through MPRIS (play, pause, toggle, next, previous)."""
        if action not in _MEDIA_ACTIONS:
            raise SystemError(
                "INVALID_ARGUMENT", "media action must be play, pause, toggle, next or previous"
            )
        self._runner.run(["playerctl", action])
        return {"media": action}

    def wifi(self, on: bool) -> dict[str, object]:
        """Turn the Wi-Fi radio on or off."""
        self._runner.run(["nmcli", "radio", "wifi", "on" if on else "off"])
        return {"wifi": on}

    def bluetooth(self, on: bool) -> dict[str, object]:
        """Turn the Bluetooth radio on or off."""
        self._runner.run(["nmcli", "radio", "bluetooth", "on" if on else "off"])
        return {"bluetooth": on}
