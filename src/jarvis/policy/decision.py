"""What the gate is asked (`ToolCall`, `TurnContext`) and what it answers (`Decision`)."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from jarvis.activity import PolicyRecord
from jarvis.config import PolicySettings
from jarvis.policy.model import Mode, Tier
from jarvis.policy.ports import Confirmer, ConsentBroker, NoConfirmer, NoConsent

Action = Literal["run", "confirm", "consent", "deny"]
Kind = Literal["voice", "click", "guardrail"]
Origin = Literal["fastpath", "brain", "internal"]
# What a tool does once the gate lets it run; only `gated_dispatch` ever calls one.
ToolImpl = Callable[[Mapping[str, object]], Awaitable[object]]


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation to be judged: the tool, its arguments and who asked for it."""

    name: str
    args: Mapping[str, object]
    origin: Origin


@dataclass(frozen=True)
class TurnContext:
    """What the gate knows about the turn the call belongs to.

    The defaults fail closed: Safe mode, a confirmer and a consent broker that say no.
    `policy_decisions` collects every decision of the turn, in order, for the activity log;
    `heard` collects what the user said in it (the command, replies), for R83.
    """

    turn_id: str
    settings: PolicySettings = field(default_factory=PolicySettings)
    mode: Mode = "safe"
    confirmer: Confirmer = field(default_factory=NoConfirmer)
    consent: ConsentBroker = field(default_factory=NoConsent)
    impls: Mapping[str, ToolImpl] = field(default_factory=dict)
    policy_decisions: list[PolicyRecord] = field(default_factory=list)
    heard: list[str] = field(default_factory=list)  # the user's words this turn (R83)


@dataclass(frozen=True)
class Decision:
    """The gate's verdict. `then_confirm` is the confirmation still due after a consent."""

    action: Action
    tier: Tier | None
    scopes: tuple[str, ...] = ()
    prompt: str | None = None
    kind: Kind | None = None
    reason: str = ""
    then_confirm: Kind | None = None
