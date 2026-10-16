"""The M1 gate: a bool verdict per call. Replaced by `decide` and `gated_dispatch` (M2 task 1)."""

from collections.abc import Mapping
from dataclasses import dataclass

from jarvis.log import audit
from jarvis.policy import registry
from jarvis.policy.model import Mode, Tier, ToolSpec
from jarvis.policy.ports import NEEDS_CONFIRMATION_REASON

_MODES = ("safe", "balanced", "yolo")


@dataclass(frozen=True)
class Decision:
    """Gate outcome."""

    allowed: bool
    reason: str


def _decide(tool: str, mode: Mode) -> tuple[Decision, str]:
    """Compute the gate decision and the tier label for logging."""
    if mode not in _MODES:
        return Decision(False, "unknown mode"), "unknown"
    if not isinstance(tool, str):
        return Decision(False, "unknown tool"), "unknown"
    spec = registry._REGISTRY.get(tool)
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
