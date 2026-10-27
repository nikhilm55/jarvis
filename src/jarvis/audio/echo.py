"""PipeWire's echo-cancelled microphone, which barge-in needs (R88, FR-ACT-09).

With `module-echo-cancel` loaded, Jarvis listens through its source while it speaks, so
"Jarvis, stop" is heard over its own voice. Without it, barge-in stays off and `jarvis doctor`
says how to turn it on (ENABLE_HINT).
"""

import shutil
import subprocess
from collections.abc import Callable

__all__ = ["ENABLE_HINT", "echo_cancel_source"]

ENABLE_HINT = (
    "Barge-in is off: no echo-cancelled microphone. To say 'Jarvis, stop' while Jarvis is "
    "talking, run: pactl load-module module-echo-cancel aec_method=webrtc "
    "source_name=echo-cancel-source sink_name=echo-cancel-sink "
    "(add it to ~/.config/pipewire/pipewire-pulse.conf.d/ to keep it after a reboot)."
)

Run = Callable[[list[str]], str]


def _pactl(argv: list[str]) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv, capture_output=True, encoding="utf-8", timeout=5, check=True
    )
    return done.stdout


def echo_cancel_source(run: Run = _pactl) -> str | None:
    """The name of the echo-cancelled source, or None when there is none (or no pactl)."""
    if run is _pactl and shutil.which("pactl") is None:
        return None
    try:
        listing = run(["pactl", "list", "short", "sources"])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    for line in listing.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        name = fields[1]
        normalised = name.lower().replace("_", "-")
        if "echo-cancel" in normalised and not name.endswith(".monitor"):
            return name
    return None
