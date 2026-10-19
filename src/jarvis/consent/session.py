"""In-memory consent grants: "once" (one command and its follow-ups) and "session" (FR-CON-09).

Nothing here is written to disk, so a crash or a restart forgets every one of them.
"""

import time
from collections.abc import Callable
from typing import Literal

from jarvis.consent.scope import Scope
from jarvis.log import audit, get_logger

logger = get_logger("consent")

SESSION_MAX_S = 8 * 3600
EndReason = Literal["brain_reset", "pc_lock", "sign_out", "revoked"]


class SessionGrants:
    """Once and session grants, with the lifetimes of FR-CON-09.

    `once` is tied to a turn's root: the turn that started a command, which its follow-up
    turns name through `start_turn(follow_up, follows=...)`. `end_turn` of the root ends it.
    `session` lasts until `end(reason)` or `SESSION_MAX_S`, by the injected clock.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._roots: dict[str, str] = {}  # turn id -> the root turn of its command
        self._once: dict[Scope, set[str]] = {}  # scope -> the roots it was allowed for
        self._session: dict[Scope, tuple[float, str]] = {}  # scope -> (granted at, root granted in)
        self._seen: set[str] = set()  # sources a YOLO run already asked about

    def start_turn(self, turn_id: str, follows: str | None = None) -> None:
        """Register a turn; a follow-up shares the root of the turn it follows."""
        self._roots[turn_id] = self.root_of(follows) if follows else turn_id

    def root_of(self, turn_id: str) -> str:
        """The root turn of `turn_id` (itself when it was never registered)."""
        return self._roots.get(turn_id, turn_id)

    def end_turn(self, turn_id: str) -> None:
        """A command and its follow-ups are over: forget their once grants and the turn ids."""
        root = self.root_of(turn_id)
        for scope in list(self._once):
            self._once[scope].discard(root)
            if not self._once[scope]:
                del self._once[scope]
        for turn in [t for t, r in self._roots.items() if r == root]:
            del self._roots[turn]

    def end(self, reason: EndReason) -> None:
        """The session is over (brain reset, PC lock, sign-out, revoke): drop everything held.

        Forgetting cannot grant anything, so an audit failure is logged and the grants are gone.
        """
        count = len(self._once) + len(self._session)
        self._once.clear()
        self._session.clear()
        self._seen.clear()
        try:
            audit("consent", "session ended", reason=reason, count=count)
        except Exception:
            logger.exception("consent audit unavailable", extra={"reason": reason})

    def grant(self, scope: Scope, lifetime: Literal["once", "session"], turn_id: str) -> None:
        """Hold a grant for `scope`, made during `turn_id`."""
        root = self.root_of(turn_id)
        if lifetime == "once":
            self._once.setdefault(scope, set()).add(root)
        else:
            self._session[scope] = (self._clock(), root)

    def revoke(self, scope: Scope) -> bool:
        """Drop the once and session grants of one scope; True when there was any."""
        removed = self._once.pop(scope, None) is not None
        return self._session.pop(scope, None) is not None or removed

    def holds(self, scope: Scope, turn_id: str, *, this_command_only: bool = False) -> bool:
        """True when `scope` is allowed for `turn_id` by a once or an unexpired session grant.

        `this_command_only` (Safe mode) ignores a session grant made in an earlier command.
        """
        root = self.root_of(turn_id)
        if root in self._once.get(scope, ()):
            return True
        held = self._session.get(scope)
        if held is None:
            return False
        granted_at, granted_in = held
        if self._clock() - granted_at >= SESSION_MAX_S:
            del self._session[scope]
            return False
        return granted_in == root or not this_command_only

    def seen(self, source: str) -> bool:
        """True when a YOLO run already asked about `source` (the first-touch switch)."""
        return source in self._seen

    def mark_seen(self, source: str) -> None:
        """Remember that `source` was asked about."""
        self._seen.add(source)
