"""Deterministic safety policy for tool calls (FRS 5.10)."""

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
)

for _spec in _DESKTOP_TOOLS:
    register(_spec)
