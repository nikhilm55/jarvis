"""Deterministic safety policy for tool calls (FRS 5.10)."""

from collections.abc import Mapping

from jarvis.policy.decide import decide
from jarvis.policy.decision import Decision, ToolCall, TurnContext
from jarvis.policy.gated import ToolResult, gated_dispatch, tool_impl
from jarvis.policy.model import Mode, Tier, ToolSpec
from jarvis.policy.ports import NEEDS_CONFIRMATION_REASON
from jarvis.policy.registry import get, register

__all__ = [
    "NEEDS_CONFIRMATION_REASON",
    "Decision",
    "Mode",
    "Tier",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "TurnContext",
    "decide",
    "gated_dispatch",
    "get",
    "register",
    "tool_impl",
]

# Keys that send, close or quit something: what a mistyped command cannot take back.
_RISKY_KEYS = {"enter", "return", "delete", "del", "f4", "w", "q"}


def _typing_tier(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
    """Text with a line break can run a command in a terminal: T2 (plan 7, FR-PC-03)."""
    text = args.get("text")
    return (Tier.T2 if isinstance(text, str) and ("\n" in text or "\r" in text) else Tier.T1), ()


def _keys_tier(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
    """Enter, Delete, and the close/quit chords (alt+f4, ctrl+w, ctrl+q) are T2."""
    combo = args.get("combo")
    if not isinstance(combo, str):
        return Tier.T2, ()
    parts = [p.strip().lower() for p in combo.split("+")]
    key, mods = parts[-1], set(parts[:-1])
    risky = key in {"enter", "return", "delete", "del"} or (
        key in _RISKY_KEYS and bool(mods & {"ctrl", "control", "alt"})
    )
    return (Tier.T2 if risky or {"ctrl", "alt"} <= mods else Tier.T1), ()


_DESKTOP_TOOLS = (
    ToolSpec("desktop.open_app", Tier.T1),
    ToolSpec("desktop.close_app", Tier.T1),
    ToolSpec("desktop.list_apps", Tier.T0),
    ToolSpec("desktop.is_running", Tier.T0),
    ToolSpec("desktop.list_windows", Tier.T0),
    ToolSpec("desktop.focus_window", Tier.T1),
    # Closing is undoable by reopening the app (R90); the undo itself is task 9's.
    ToolSpec("desktop.window_op", Tier.T1, undoable=True),
    ToolSpec("desktop.volume_get", Tier.T0),
    # FRS 5.10 lists volume under T1; reading it is T0 (R95).
    ToolSpec("desktop.volume_set", Tier.T1),
    ToolSpec("desktop.volume_step", Tier.T1),
    ToolSpec("desktop.mute", Tier.T1),
    # FR-PC-03 input; each drives the input, so the HUD says so (FR-SAFE-06). Typed text the
    # user did not say is confirmed even in YOLO (R83).
    ToolSpec(
        "desktop.type_text",
        Tier.T1,
        classify=_typing_tier,
        provenance_keys=("text",),
        drives_input=True,
    ),
    ToolSpec("desktop.press_keys", Tier.T1, classify=_keys_tier, drives_input=True),
    ToolSpec("desktop.click", Tier.T2, drives_input=True),  # coordinates can land on anything
    ToolSpec("desktop.scroll", Tier.T1, drives_input=True),
)

for _spec in _DESKTOP_TOOLS:
    register(_spec)
