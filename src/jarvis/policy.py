"""Deterministic safety gate for voice-controlled desktop assistant tool calls."""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from jarvis.log import get_logger

_MODES = ("safe", "balanced", "yolo")


class Tier(enum.StrEnum):
    """Tool risk tiers."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


@dataclass(frozen=True)
class ToolSpec:
    """Immutable tool descriptor."""

    name: str
    tier: Tier
    scopes: tuple[str, ...] = ()


_REGISTRY: dict[str, ToolSpec] = {}


@dataclass(frozen=True)
class Decision:
    """Gate outcome."""

    allowed: bool
    reason: str


Mode = Literal["safe", "balanced", "yolo"]


def register(spec: ToolSpec) -> None:
    """Add a tool spec to the registry."""
    existing = _REGISTRY.get(spec.name)
    if existing is not None:
        if existing == spec:
            return
        raise ValueError(f"conflicting registration for {spec.name!r}")
    _REGISTRY[spec.name] = spec


def get(name: str) -> ToolSpec | None:
    """Look up a registered tool spec."""
    return _REGISTRY.get(name)


def _decide(tool: str, mode: Mode) -> tuple[Decision, str]:
    """Compute the gate decision and the tier label for logging."""
    if mode not in _MODES:
        return Decision(False, "unknown mode"), "unknown"
    if not isinstance(tool, str):
        return Decision(False, "unknown tool"), "unknown"
    spec = _REGISTRY.get(tool)
    if spec is None:
        return Decision(False, "unknown tool"), "unknown"
    return _decide_spec(spec, mode)


def _decide_spec(spec: ToolSpec, mode: Mode) -> tuple[Decision, str]:
    """Evaluate a resolved tool spec against the active mode."""
    if spec.scopes:
        return Decision(False, "consent layer not built yet (M2)"), spec.tier.value
    if mode == "safe" and spec.tier == Tier.T1:
        # FRS 5.10: Safe mode confirms T1; the confirmation layer arrives in M2.
        return Decision(False, "needs confirmation (M2)"), spec.tier.value
    if spec.tier in (Tier.T0, Tier.T1):
        return Decision(True, f"allowed: {spec.tier.value}"), spec.tier.value
    return Decision(False, "needs confirmation - M2"), spec.tier.value


def gate(tool: str, args: Mapping[str, object], mode: Mode) -> Decision:
    """Evaluate one tool call against the safety gate."""
    decision, tier = _decide(tool, mode)
    get_logger("jarvis.policy").info(
        "policy decision",
        extra={
            "tool": tool,
            "tier": tier,
            "mode": mode,
            "decision": "allow" if decision.allowed else "deny",
            "reason": decision.reason,
        },
    )
    return decision


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
