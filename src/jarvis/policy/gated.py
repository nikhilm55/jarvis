"""`gated_dispatch`: the only path from any caller to a tool implementation (FR-SAFE-01, 10).

It decides, asks (confirmation, consent), writes the audit record, runs the tool and records
the outcome. Every failure on the way is a refusal; an allow is returned only after its audit
record is on disk.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from jarvis.activity import PolicyRecord
from jarvis.contract import ErrorInfo
from jarvis.contract.models import ErrorCode
from jarvis.log import audit, get_logger
from jarvis.policy import registry
from jarvis.policy.decide import decide
from jarvis.policy.decision import Decision, Kind, ToolCall, ToolImpl, TurnContext, not_shown
from jarvis.policy.lists import (
    UNRESOLVABLE_REASON,
    command_of,
    path_args,
    shell_targets,
    speak_targets,
)
from jarvis.policy.model import Tier
from jarvis.policy.ports import (
    CONFIRMATION_UNAVAILABLE_REASON,
    NEEDS_CONFIRMATION_REASON,
    NoConfirmer,
)
from jarvis.policy.prompts import describe
from jarvis.policy.provenance import foreign_values

__all__ = ["ToolResult", "gated_dispatch", "tool_impl"]

logger = get_logger("policy")
_T = TypeVar("_T", bound=ToolImpl)


def tool_impl(name: str) -> Callable[[_T], _T]:
    """Mark a function as the implementation of tool `name`: only `gated_dispatch` may call it.

    The name travels with the function, so an impl filed under another tool's name (and so
    judged at that tool's tier) is refused.
    """

    def mark(fn: _T) -> _T:
        fn.tool_name = name  # type: ignore[attr-defined]
        return fn

    return mark


MISMATCHED_IMPL_REASON = "policy error: that implementation belongs to another tool"


@dataclass(frozen=True)
class ToolResult:
    """What `gated_dispatch` returns: the tool's output, or the refusal."""

    output: object = None
    error: ErrorInfo | None = None
    decision: Decision | None = None


@dataclass(frozen=True)
class _Verdict:
    allowed: bool
    decision: Decision
    reason: str
    code: ErrorCode = "BLOCKED_BY_POLICY"
    confirmed_by: str | None = None
    consent_checked: bool = False  # the broker was asked about this call's scopes


def _consent_remedy(scopes: tuple[str, ...]) -> str:
    """FR-CON-08: how to change your mind, naming each source ("messages.teams" -> "teams")."""
    names = sorted({s.partition(":")[0].rpartition(".")[2] for s in scopes} - {""})
    allow = " or ".join(f"'Jarvis, allow {name}'" for name in names) or "'Jarvis, allow <source>'"
    return f"Say {allow}, or turn it on in Settings → Permissions."


def _refusal(verdict: _Verdict) -> ToolResult:
    remedy = {
        "CONSENT_DENIED": _consent_remedy(verdict.decision.scopes),
        "CANCELLED": "Ask again if you do want it done.",
    }.get(verdict.code, "Check the activity log for the reason.")
    if verdict.reason == UNRESOLVABLE_REASON:
        remedy = "Say the exact path, so it can be checked against your protected folders."
    error = ErrorInfo(
        code=verdict.code,
        what="The safety check refused that action",
        why=verdict.reason,
        remedy=[remedy],
    )
    return ToolResult(error=error, decision=verdict.decision)


def _target_phrase(call: ToolCall) -> str:
    """The words the user repeats to confirm a T3 action in YOLO: "confirm <verb> <targets>".

    Every target is named (more than three become "N paths in <dir>"). For a shell command the
    verb is its command and the targets its non-option words; for another tool the verb is the
    tool's name and the targets are what its spec's `target_key` points at, else its paths.
    """
    cmd = command_of(call.args)
    if cmd:
        verb, targets = shell_targets(cmd)
    else:
        spec = registry.get(call.name)
        verb = call.name.rsplit(".", 1)[-1].replace("_", " ")
        declared = call.args.get(spec.target_key) if spec and spec.target_key else None
        if isinstance(declared, str):
            targets = [declared]
        elif isinstance(declared, list):
            targets = [t for t in declared if isinstance(t, str)]
        else:
            targets = path_args(call.args)
    return speak_targets(verb, targets)


_MAX_QUOTE = 60


def _provenance(call: ToolCall, ctx: TurnContext, decision: Decision) -> tuple[Decision, str]:
    """R83: a brain's T2+ call whose target the user did not say is confirmed in every mode.

    Returns the decision (a run becomes a voice confirmation) and the note the question starts
    with, naming where the value came from; no note when the values are the user's own.
    """
    spec = registry.get(call.name)
    if call.origin != "brain" or decision.tier not in (Tier.T2, Tier.T3) or spec is None:
        return decision, ""
    foreign = foreign_values(spec, call.args, ctx.heard)
    if not foreign:
        return decision, ""
    shown = foreign[0] if len(foreign[0]) <= _MAX_QUOTE else foreign[0][: _MAX_QUOTE - 1] + "…"
    note = f"You didn't say '{shown}': it came from something I read."
    if decision.action == "run":  # YOLO; Safe and Balanced already confirm every T2+ call
        reason = "content-derived target needs confirmation (R83)"
        decision = replace(decision, action="confirm", kind="voice", reason=reason)
    return decision, note


async def _confirm(
    call: ToolCall, ctx: TurnContext, decision: Decision, kind: Kind, note: str = ""
) -> _Verdict:
    phrase = _target_phrase(call) if kind == "guardrail" else None
    prompt = describe(call.name, call.args, decision.tier)  # a consent's prompt asked for scopes
    prompt = f"{note} {prompt}" if note else prompt
    answer = await ctx.confirmer.ask(prompt, kind, phrase)
    if answer.yes is True:  # anything else, a truthy string included, is not a yes
        return _Verdict(True, decision, "confirmed", confirmed_by=answer.method)
    if isinstance(ctx.confirmer, NoConfirmer):
        reason = (
            NEEDS_CONFIRMATION_REASON
            if decision.tier == Tier.T1
            else CONFIRMATION_UNAVAILABLE_REASON
        )
        return _Verdict(False, decision, reason)
    if answer.method == "timeout":
        return _Verdict(False, decision, "no answer to the confirmation")
    return _Verdict(False, decision, "you declined", code="CANCELLED", confirmed_by=answer.method)


def _mismatch(call: ToolCall, ctx: TurnContext) -> _Verdict | None:
    """A refusal when the impl filed under this name was registered for another tool."""
    impl = ctx.impls.get(call.name)
    if impl is not None and getattr(impl, "tool_name", None) != call.name:
        return _Verdict(False, Decision("deny", None), MISMATCHED_IMPL_REASON)
    return None


async def _judge(call: ToolCall, ctx: TurnContext) -> _Verdict:
    decision = await asyncio.to_thread(decide, call, ctx.mode, ctx)
    if decision.action == "deny":
        return _Verdict(False, decision, decision.reason)
    decision, note = _provenance(call, ctx, decision)
    # Any verdict that names scopes must be checked against the broker first (FR-CON-10):
    # "never" beats every mode at every tier, including YOLO confirm/guardrail.
    checked = bool(decision.scopes)
    if (
        checked
        and await ctx.consent.require(decision.scopes, "", ctx) != "granted"  # "To do that…"
    ):
        return _Verdict(False, decision, "consent denied", code="CONSENT_DENIED")
    return replace(await _after_consent(call, ctx, decision, note), consent_checked=checked)


async def _after_consent(
    call: ToolCall, ctx: TurnContext, decision: Decision, note: str = ""
) -> _Verdict:
    if decision.action == "run":
        return _Verdict(True, decision, decision.reason)
    if decision.action == "consent":
        if decision.then_confirm is None:
            return _Verdict(True, decision, "consent granted")
        return await _confirm(call, ctx, decision, decision.then_confirm, note)
    if decision.kind is None:
        raise ValueError("a confirm decision needs a kind")
    return await _confirm(call, ctx, decision, decision.kind, note)


def _write_audit(call: ToolCall, ctx: TurnContext, verdict: _Verdict) -> None:
    decision = verdict.decision
    audit(
        "policy",
        "policy decision",
        turn_id=ctx.turn_id,
        tool=call.name,
        origin=call.origin,
        tier=decision.tier.value if decision.tier else "unknown",
        mode=ctx.mode,
        action=decision.action,
        decision="allow" if verdict.allowed else "deny",
        scopes=",".join(decision.scopes),
        confirmed_by=verdict.confirmed_by,
        reason=verdict.reason,
    )


async def _authorise(call: ToolCall, ctx: TurnContext) -> _Verdict:
    """Judge the call and audit the verdict; any failure, an unwritable audit log too, denies."""
    deny = Decision("deny", None)
    try:
        verdict = _mismatch(call, ctx) or await _judge(call, ctx)
        if verdict.allowed and verdict.decision.scopes and not verdict.consent_checked:
            raise RuntimeError("allowed with scopes but no consent check")  # an invariant
    except Exception as exc:
        verdict = _Verdict(False, deny, f"policy error: {type(exc).__name__}")
    try:
        await asyncio.to_thread(_write_audit, call, ctx, verdict)
    except Exception:
        logger.exception("audit unavailable", extra={"tool": call.name})
        verdict = _Verdict(False, verdict.decision, "policy error: audit unavailable")
    tier = verdict.decision.tier
    ctx.policy_decisions.append(
        PolicyRecord(
            call.name,
            verdict.allowed,
            verdict.reason,
            tier.value if tier else None,
            verdict.confirmed_by,
        )
    )
    return verdict


def _write_outcome(call: ToolCall, ctx: TurnContext, outcome: str) -> None:
    audit("policy", "tool outcome", turn_id=ctx.turn_id, tool=call.name, outcome=outcome)


async def _outcome(call: ToolCall, ctx: TurnContext, outcome: str) -> None:
    """Record how the tool ended; the tool already ran, so a failed write cannot undo it."""
    try:
        await asyncio.to_thread(_write_outcome, call, ctx, outcome)
    except Exception:
        logger.exception("outcome audit failed", extra={"tool": call.name})


async def gated_dispatch(call: ToolCall, ctx: TurnContext) -> ToolResult:
    """Run `call` if the policy lets it, asking for confirmation or consent first.

    A refusal comes back as `ToolResult.error`. An exception raised by the tool itself is
    recorded in the audit log and re-raised, so callers keep their own error handling.
    """
    verdict = await _authorise(call, ctx)
    if not verdict.allowed:
        return _refusal(verdict)
    impl = ctx.impls.get(call.name)
    if impl is None:
        await _outcome(call, ctx, "error: no implementation")
        error = ErrorInfo(
            code="INTERNAL",
            what="That tool is not available",
            why=f"no implementation is registered for {call.name}",
            remedy=["Report this to the Jarvis developers."],
        )
        return ToolResult(error=error, decision=verdict.decision)
    spec = registry.get(call.name)
    indicator = ctx.controlling() if spec is not None and spec.drives_input else not_shown()
    try:
        async with indicator:
            output = await impl(call.args)
    except Exception as exc:
        await _outcome(call, ctx, f"error: {type(exc).__name__}")
        raise
    await _outcome(call, ctx, "ok")
    return ToolResult(output=output, decision=verdict.decision)
