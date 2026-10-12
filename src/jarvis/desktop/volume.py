"""Thin wrappers over PipeWire's wpctl CLI for the default audio sink."""

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

SINK = "@DEFAULT_AUDIO_SINK@"

_VOLUME_RE = re.compile(r"^Volume:\s*([0-9]+(?:\.[0-9]+)?)(\s+\[MUTED\])?\s*$")


class VolumeError(Exception):
    """Raised when a wpctl operation fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class VolumeState:
    """Snapshot of the default audio sink volume."""

    percent: int
    muted: bool


Runner = Callable[[Sequence[str]], str]


def run_wpctl(args: Sequence[str]) -> str:
    """Execute wpctl with the given arguments and return stdout."""
    try:
        result = subprocess.run(  # noqa: S603
            ["wpctl", *args],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VolumeError("UNSUPPORTED_ON_PLATFORM", "wpctl is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise VolumeError("TIMEOUT", "wpctl timed out") from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise VolumeError("INTERNAL", "wpctl failed: " + stderr[:200])
    return result.stdout


def parse_volume(text: str) -> VolumeState:
    """Parse wpctl get-volume output into a VolumeState."""
    match = _VOLUME_RE.match(text.strip())
    if match is None:
        raise VolumeError("INTERNAL", "unexpected wpctl output")
    fraction = float(match.group(1))
    muted = match.group(2) is not None
    return VolumeState(percent=round(fraction * 100), muted=muted)


def volume_get(runner: Runner = run_wpctl) -> VolumeState:
    """Get the current volume state of the default audio sink."""
    return parse_volume(runner(["get-volume", SINK]))


def volume_set(percent: int, runner: Runner = run_wpctl) -> VolumeState:
    """Set the volume to an absolute percentage (0-100)."""
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise VolumeError("INTERNAL", "percent must be an integer")
    clamped = max(0, min(100, percent))
    runner(["set-volume", "-l", "1.0", SINK, f"{clamped / 100:.2f}"])
    return volume_get(runner)


def volume_step(delta: int, runner: Runner = run_wpctl) -> VolumeState:
    """Adjust the volume by a relative percentage step."""
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise VolumeError("INTERNAL", "delta must be an integer")
    clamped = max(-100, min(100, delta))
    if clamped == 0:
        return volume_get(runner)
    sign = "+" if clamped > 0 else "-"
    runner(["set-volume", "-l", "1.0", SINK, f"{abs(clamped)}%{sign}"])
    return volume_get(runner)


def set_mute(on: bool, runner: Runner = run_wpctl) -> VolumeState:
    """Mute or unmute the default audio sink."""
    if not isinstance(on, bool):
        raise VolumeError("INTERNAL", "on must be a boolean")
    runner(["set-mute", SINK, "1" if on else "0"])
    return volume_get(runner)
