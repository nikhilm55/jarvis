"""`jarvis.request_access(scopes, reason)`: the brain asks once, up front, for a task (FR-CON-03).

It is a T0 tool whose scopes are its own arguments, so the gate's consent step asks for all of
them in one question (with the brain's reason), says yes at once in YOLO or when they are
already granted, and refuses with CONSENT_DENIED otherwise. Once the gate lets it run, every
scope is granted.
"""

from collections.abc import Mapping

from jarvis.consent.scope import parse_scopes
from jarvis.policy import Tier, ToolSpec, register

__all__ = ["MAX_SCOPES", "REQUEST_ACCESS", "requested_scopes"]

REQUEST_ACCESS = "jarvis.request_access"
MAX_SCOPES = 20


def requested_scopes(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
    """The classifier: the scopes asked for; a malformed list raises, which the gate denies."""
    items = args.get("scopes")
    if not isinstance(items, list) or not items or len(items) > MAX_SCOPES:
        raise ValueError(f"scopes must be a list of 1 to {MAX_SCOPES} scope names")
    if not all(isinstance(item, str) for item in items):
        raise ValueError("every scope must be a string such as messages.teams:read")
    return Tier.T0, tuple(str(scope) for scope in parse_scopes(items))


register(ToolSpec(REQUEST_ACCESS, Tier.T0, classify=requested_scopes, reason_key="reason"))
