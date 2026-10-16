"""Ports the gate asks through: task 2 plugs in the Confirmer, task 3 the ConsentBroker.

The defaults say no, so until those tasks land a call that needs either one is refused.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from jarvis.policy.decision import Kind, TurnContext

# Why a call was refused when nothing could ask the user; callers compare it by equality (R39-R41).
NEEDS_CONFIRMATION_REASON = "needs confirmation (M2)"

Method = Literal["voice", "typed", "button", "key", "timeout"]


@dataclass(frozen=True)
class Answer:
    """The user's answer to a confirmation, and how it arrived."""

    yes: bool
    method: Method


class Confirmer(Protocol):
    """Asks the user to confirm one action (FR-SAFE-07)."""

    async def ask(
        self, prompt: str, kind: "Kind", target_phrase: str | None = None, timeout_s: float = 15
    ) -> Answer: ...


class ConsentBroker(Protocol):
    """Gets consent for scopes (FRS 5.11); `granted` only when every scope is allowed."""

    async def require(
        self, scopes: tuple[str, ...], reason: str, ctx: "TurnContext"
    ) -> Literal["granted", "denied"]: ...


class NoConfirmer:
    """Answers no to everything: nothing that needs a confirmation runs."""

    async def ask(
        self, prompt: str, kind: "Kind", target_phrase: str | None = None, timeout_s: float = 15
    ) -> Answer:
        return Answer(False, "timeout")


class NoConsent:
    """Denies every consent request."""

    async def require(
        self, scopes: tuple[str, ...], reason: str, ctx: "TurnContext"
    ) -> Literal["granted", "denied"]:
        return "denied"
