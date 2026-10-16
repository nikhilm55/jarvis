"""Deterministic safety policy for tool calls (FRS 5.10)."""

from jarvis.policy.legacy import NEEDS_CONFIRMATION_REASON, Decision, gate
from jarvis.policy.model import Mode, Tier, ToolSpec
from jarvis.policy.registry import get, register

__all__ = [
    "NEEDS_CONFIRMATION_REASON",
    "Decision",
    "Mode",
    "Tier",
    "ToolSpec",
    "gate",
    "get",
    "register",
]

_DESKTOP_TOOLS = (
    ToolSpec("desktop.open_app", Tier.T1),
    ToolSpec("desktop.close_app", Tier.T1),
    ToolSpec("desktop.volume_get", Tier.T0),
    ToolSpec("desktop.volume_set", Tier.T0),
    ToolSpec("desktop.volume_step", Tier.T0),
    ToolSpec("desktop.mute", Tier.T0),
)

for _spec in _DESKTOP_TOOLS:
    register(_spec)
