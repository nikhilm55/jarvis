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
from pathlib import Path
from typing import Protocol

__all__ = ["CommandResult", "Runner", "SystemControls", "SystemError"]

# Long enough for a login1/GNOME D-Bus round trip on a cold session, short enough
# that a stuck backend cannot hold a turn.
_TIMEOUT_S = 10

_POWER_SUPPLY_DIR = Path("/sys/class/power_supply")

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
_POWER_ACTIONS = ("sleep", "signout", "restart", "shutdown")

_LOGIN1 = (
    "gdbus",
    "call",
    "--system",
    "--dest",
    "org.freedesktop.login1",
    "--object-path",
    "/org/freedesktop/login1",
    "--method",
    "org.freedesktop.login1.Manager.",
)


def _read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _parse_sinks(status: str) -> list[tuple[int, str]]:
    """The numbered entries under `Sinks:` in `wpctl status` (index, name)."""
    sinks: list[tuple[int, str]] = []
    looking = False
    for line in status.splitlines():
        stripped = line.strip()
        if stripped.startswith("Sinks:"):
            looking = True
            continue
        if looking:
            if not stripped or (stripped.endswith(":") and not stripped[0].isdigit()):
                looking = False
                continue
            head, _, name = stripped.partition(". ")
            if name and head.strip(" *").isdigit():
                sinks.append((int(head.strip(" *").strip()), name))
    return sinks


def _active_sink(status: str) -> int | None:
    """The index of the marked (`*`) sink in `wpctl status`, if listed."""
    for line in status.splitlines():
        stripped = line.strip()
        if stripped.startswith("* "):
            head, _, _ = stripped[2:].partition(". ")
            if head.isdigit():
                return int(head)
    return None


class SystemControls:
    """One validated argument set per control; the command lines are fixed."""

    def __init__(self, runner: Runner) -> None:
        """Take a backend runner (the OS runner, or a fake in tests)."""
        self._runner = runner

    def output_device(self, device: int) -> dict[str, object]:
        """List the output sinks (device 0), or switch to the numbered one."""
        status = self._runner.run(["wpctl", "status"]).stdout
        if device == 0:
            return {
                "devices": [f"{i}. {n}" for i, n in _parse_sinks(status)],
                "active": _active_sink(status),
            }
        for index, name in _parse_sinks(status):
            if index == device:
                self._runner.run(["wpctl", "set-default", str(index)])
                return {"set": f"{index}. {name}"}
        raise SystemError("NOT_FOUND", f"no output device with index {device} — list them first")

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

    def lock(self) -> dict[str, object]:
        """Lock the session through the GNOME screensaver bus."""
        self._runner.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.ScreenSaver",
                "--object-path",
                "/org/gnome/ScreenSaver",
                "--method",
                "org.gnome.ScreenSaver.Lock",
            ]
        )
        return {"locked": True}

    def power(self, action: str) -> dict[str, object]:
        """Sleep, sign out, restart or shut down — T3, the owner confirms these."""
        if action == "signout":
            self._runner.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.SessionManager",
                    "--object-path",
                    "/org/gnome/SessionManager",
                    "--method",
                    "org.gnome.SessionManager.Logout",
                    "0",
                ]
            )
            return {"power": action}
        if action not in _POWER_ACTIONS:
            raise SystemError(
                "INVALID_ARGUMENT", "power action must be sleep, signout, restart or shutdown"
            )
        method = {"sleep": "Sleep", "restart": "Reboot", "shutdown": "PowerOff"}[action]
        self._runner.run([*_LOGIN1[:-1], f"{_LOGIN1[-1]}{method}"])
        return {"power": action}

    def open_url(self, url: str) -> dict[str, object]:
        """Open one validated URL in the owner's browser (http/https only)."""
        self._runner.run(["xdg-open", url])
        return {"opened": url}

    def info(self) -> dict[str, object]:
        """Battery, memory, disk and uptime (FR-PC-13); kernel files only, no commands."""
        battery = None
        for supply in sorted(_POWER_SUPPLY_DIR.glob("BAT*")):
            raw = (supply / "capacity").read_text(encoding="utf-8").strip()
            if not raw.isdigit():
                raise SystemError("INTERNAL", f"unreadable battery level in {supply}/capacity")
            battery = int(raw)
        mem: dict[str, int] = {}
        for line in _read_file("/proc/meminfo").splitlines():
            key, _, value = line.partition(":")
            mem[key] = int(value.split()[0])
        total = mem.get("MemTotal", 0)
        free = mem.get("MemAvailable", 0)
        usage = shutil.disk_usage("/")
        return {
            "battery": battery,
            "memory_used_percent": round(100 * (total - free) / total, 1) if total else None,
            "disk_used_percent": round(usage.used / usage.total * 100, 1),
            "uptime_s": round(float(_read_file("/proc/uptime").split()[0])),
        }
