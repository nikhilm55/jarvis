"""What the gate is asked (`ToolCall`, `TurnContext`) and what it answers (`Decision`)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from jarvis.config import PolicySettings
from jarvis.policy.model import Tier

Action = Literal["run", "confirm", "consent", "deny"]
Kind = Literal["voice", "click", "guardrail"]
Origin = Literal["fastpath", "brain", "internal"]


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation to be judged: the tool, its arguments and who asked for it."""

    name: str
    args: Mapping[str, object]
    origin: Origin


@dataclass(frozen=True)
class TurnContext:
    """What the gate knows about the turn the call belongs to."""

    turn_id: str
    settings: PolicySettings = field(default_factory=PolicySettings)


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
