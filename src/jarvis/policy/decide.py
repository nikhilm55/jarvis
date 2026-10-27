"""The policy gate: turn a tool call into run / confirm / consent / deny (FRS 5.10)."""

from jarvis.policy import lists, registry
from jarvis.policy.decision import Action, Decision, Kind, ToolCall, TurnContext
from jarvis.policy.model import Mode, Tier, max_tier
from jarvis.policy.prompts import describe

_TABLE: dict[Mode, dict[Tier, tuple[Action, Kind | None]]] = {
    "safe": {
        Tier.T0: ("run", None),
        Tier.T1: ("confirm", "voice"),
        Tier.T2: ("confirm", "voice"),
        Tier.T3: ("confirm", "click"),
    },
    "balanced": {
        Tier.T0: ("run", None),
        Tier.T1: ("run", None),
        Tier.T2: ("confirm", "voice"),
        Tier.T3: ("confirm", "click"),
    },
    "yolo": {
        Tier.T0: ("run", None),
        Tier.T1: ("run", None),
        Tier.T2: ("run", None),
        Tier.T3: ("confirm", "guardrail"),
    },
}


def _decide(call: ToolCall, mode: Mode, ctx: TurnContext) -> Decision:
    if mode not in _TABLE:
        return Decision("deny", None, reason="unknown mode")

    spec = registry.get(call.name) if isinstance(call.name, str) else None
    if spec is None:
        return Decision("deny", None, reason="unknown tool")

    tier = spec.tier
    scopes: set[str] = set(spec.scopes)

    if spec.classify is not None:
        classified_tier, classified_scopes = spec.classify(call.args)
        tier = max_tier(tier, classified_tier)
        scopes.update(classified_scopes)

    deny_reason = lists.denied(call.args, ctx.settings)
    if deny_reason is not None:
        return Decision("deny", tier, tuple(sorted(scopes)), reason=deny_reason)

    access = "read" if tier == Tier.T0 else "write"
    scopes.update(lists.path_scopes(call.args, access, ctx.settings))
    scopes_tuple = tuple(sorted(scopes))

    action, kind = _TABLE[mode][tier]

    if scopes_tuple and mode in ("safe", "balanced"):
        prompt = f"Allow {call.name} to use {', '.join(scopes_tuple)}?"
        then_confirm: Kind | None = kind if action == "confirm" else None
        return Decision(
            "consent",
            tier,
            scopes_tuple,
            prompt=prompt,
            reason="consent needed",
            then_confirm=then_confirm,
        )

    if action == "confirm":
        return Decision(
            "confirm",
            tier,
            scopes_tuple,
            prompt=describe(call.name, call.args, tier),
            kind=kind,
            reason=f"{tier.value} in {mode} mode needs confirmation",
        )

    reason = "auto-allowed: YOLO" if scopes_tuple else f"allowed: {tier.value}"
    return Decision("run", tier, scopes_tuple, reason=reason)


def decide(call: ToolCall, mode: Mode, ctx: TurnContext) -> Decision:
    """Judge one tool call against the mode table; every doubt or error denies."""
    try:
        return _decide(call, mode, ctx)
    except Exception as exc:
        return Decision("deny", None, reason=f"policy error: {type(exc).__name__}")
