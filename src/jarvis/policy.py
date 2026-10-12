"""Deterministic safety gate for voice-controlled desktop assistant tool calls."""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from jarvis.log import audit

_MODES = ("safe", "balanced", "yolo")

# The reason of the safe-mode T1 denial; callers compare against it by equality.
NEEDS_CONFIRMATION_REASON = "needs confirmation (M2)"


class Tier(enum.StrEnum):
    """Tool risk tiers."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


def _check_name(value: object) -> str:
    """Validate and return a non-blank tool name."""
    if not isinstance(value, str):
        raise ValueError("invalid name: must be a str")
    if not value.strip():
        raise ValueError("invalid name: must be non-blank")
    return value


def _check_tier(value: object) -> Tier:
    """Validate and normalise a tier value."""
    if isinstance(value, Tier):
        return value
    if isinstance(value, str):
        try:
            return Tier(value)
        except ValueError as exc:
            raise ValueError(f"invalid tier {value!r}") from exc
    raise ValueError(f"invalid tier {value!r}")


def _check_scopes(value: object) -> tuple[str, ...]:
    """Validate and normalise scopes to a tuple of strings."""
    if isinstance(value, str) or value is None:
        raise ValueError("invalid scopes: must be a list or tuple")
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid scopes: must be a list or tuple")
    for item in value:
        if not isinstance(item, str):
            raise ValueError("invalid scopes: items must be str")
    return tuple(value)


@dataclass(frozen=True)
class ToolSpec:
    """Immutable tool descriptor."""

    name: str
    tier: Tier
    scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalise fields on construction."""
        object.__setattr__(self, "name", _check_name(self.name))
        object.__setattr__(self, "tier", _check_tier(self.tier))
        object.__setattr__(self, "scopes", _check_scopes(self.scopes))


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
        return Decision(False, NEEDS_CONFIRMATION_REASON), spec.tier.value
    if spec.tier in (Tier.T0, Tier.T1):
        return Decision(True, f"allowed: {spec.tier.value}"), spec.tier.value
    return Decision(False, "needs confirmation - M2"), spec.tier.value


def gate(tool: str, args: Mapping[str, object], mode: Mode) -> Decision:
    """Evaluate one tool call against the safety gate.

    Fails closed: any error, including an unwritable audit log, is a deny.
    The audit record must be written (a raising audit path in jarvis.log)
    before an allow is returned.
    """
    try:
        decision, tier = _decide(tool, mode)
        try:
            audit(
                "policy",
                "policy decision",
                tool=tool,
                tier=tier,
                mode=mode,
                decision="allow" if decision.allowed else "deny",
                reason=decision.reason,
            )
        except Exception:
            return Decision(False, "policy error: audit unavailable")
        return decision
    except Exception as exc:
        return Decision(False, f"policy error: {type(exc).__name__}")


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
