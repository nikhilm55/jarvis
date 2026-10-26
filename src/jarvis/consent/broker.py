"""The consent broker: may Jarvis touch this scope? (FRS 5.11.3, FR-CON-02..11, 17).

The order never changes: a "never" grant or a deny-listed path says no first, YOLO says yes,
then the grants held, then one question for everything still missing. Every doubt, an error
and an unwritable audit log included, is a no.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, cast

from jarvis.config import ConsentSettings
from jarvis.consent.scope import Scope, ScopeError, parse_scopes
from jarvis.consent.session import NO_TURN, SessionGrants
from jarvis.consent.store import Grant, GrantMethod, GrantStore, Lifetime
from jarvis.log import audit, get_logger
from jarvis.paths import data_dir
from jarvis.policy import lists

if TYPE_CHECKING:
    from jarvis.policy.decision import TurnContext

logger = get_logger("consent")

Choice = Literal["once", "session", "always", "no", "never", "timeout"]
AnswerMethod = Literal["voice", "typed", "button", "key", "timeout"]
_CHOICES = ("once", "session", "always", "no", "never", "timeout")
_GRANT_METHODS = ("voice", "typed", "button", "key")


@dataclass(frozen=True)
class AskAnswer:
    """The user's answer to a consent question, and how it arrived."""

    choice: Choice
    method: AnswerMethod


class Asker(Protocol):
    """Asks the user for consent (voice and HUD card, task 4)."""

    async def ask(
        self, scopes: tuple[Scope, ...], reason: str, ctx: "TurnContext", offer_always: bool
    ) -> AskAnswer: ...


class NoAsker:
    """Nobody to ask: every question times out, which is a no."""

    async def ask(
        self, scopes: tuple[Scope, ...], reason: str, ctx: "TurnContext", offer_always: bool
    ) -> AskAnswer:
        return AskAnswer("timeout", "timeout")


@dataclass(frozen=True)
class Consent:
    """The pieces the product wires together: the broker and the session grants it consults."""

    broker: "Broker"
    session: SessionGrants


def build_consent(settings: ConsentSettings, asker: Asker | None = None) -> Consent:
    """The real broker over `data_dir()/grants.json`; with no asker nothing ungranted is allowed."""
    session = SessionGrants()
    store = GrantStore(data_dir() / "grants.json")
    return Consent(Broker(store, session, asker or NoAsker(), settings), session)


@dataclass(frozen=True)
class _Outcome:
    """What a step decided; `decision` is "asking" only in the record of the question."""

    decision: Literal["granted", "denied", "asking"]
    reason: str
    method: str = "none"


def _granted(reason: str, method: str) -> _Outcome:
    return _Outcome("granted", reason, method)


def _denied(reason: str, method: str = "none") -> _Outcome:
    return _Outcome("denied", reason, method)


def _nothing() -> None:
    """The step of an answer that changes no grant."""


class Broker:
    """Implements `policy.ports.ConsentBroker` over a grants store and the session's grants."""

    def __init__(
        self,
        store: GrantStore,
        session: SessionGrants,
        asker: Asker,
        settings: ConsentSettings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._session = session
        self._asker = asker
        self._settings = settings
        self._clock = clock

    async def require(
        self,
        scopes: tuple[str, ...],
        reason: str,
        ctx: "TurnContext",
        *,
        args: Mapping[str, object] | None = None,
    ) -> Literal["granted", "denied"]:
        """`granted` only when every scope is allowed; `args` are checked against the deny list."""
        try:
            outcome = await self._resolve(scopes, reason, ctx, args)
        except Exception as exc:
            logger.exception("consent check failed")
            outcome = _denied(f"error: {type(exc).__name__}")
        if outcome.decision == "granted" and ctx.mode == "yolo":
            for scope in parse_scopes(scopes):
                self._session.mark_seen(scope.source)  # the first-touch switch asks once each
        try:
            self._audit(ctx, scopes, "consent check", outcome)
        except Exception:
            logger.exception("consent audit unavailable")
            return "denied"
        return "granted" if outcome.decision == "granted" else "denied"

    def revoke(self, scope: Scope) -> bool:
        """Remove every grant of `scope`, stored or held in memory."""
        removed = self._store.revoke(scope)
        return self._session.revoke(scope) or removed

    def revoke_all(self) -> None:
        """Forget every allowance, stored or held in memory ("never" entries stay)."""
        self._store.revoke_all()
        self._session.end("revoked")

    def reset_all_to_ask(self) -> None:
        """Forget every grant and every "never": all scopes ask again."""
        self._store.reset_all_to_ask()
        self._session.end("revoked")

    def _audit(
        self, ctx: "TurnContext", scopes: tuple[str, ...], message: str, outcome: _Outcome
    ) -> None:
        audit(
            "consent",
            message,
            turn_id=ctx.turn_id,
            scopes=",".join(scopes),
            mode=ctx.mode,
            decision=outcome.decision,
            method=outcome.method,
            reason=outcome.reason,
        )

    def _expired(self, grant: Grant) -> bool:
        days = self._settings.always_expiry_days
        return days is not None and self._clock() - grant.granted_at >= timedelta(days=days)

    def _never(self, scopes: tuple[Scope, ...]) -> Scope | None:
        for scope in scopes:
            grant = self._store.get(scope)
            if grant is not None and grant.lifetime == "never":
                return scope
        return None

    def _allowed(self, scope: Scope, turn_id: str, safe: bool) -> bool:
        """A valid grant for `scope` now; Safe mode honours only this command's own."""
        if self._session.holds(scope, turn_id, this_command_only=safe):
            return True
        grant = None if safe else self._store.get(scope)
        return grant is not None and grant.lifetime == "always" and not self._expired(grant)

    async def _refused(
        self, scopes: tuple[Scope, ...], ctx: "TurnContext", args: Mapping[str, object] | None
    ) -> _Outcome | None:
        """A "never" scope or a deny-listed path says no before anything else is asked."""
        blocked = self._never(scopes)
        if blocked is not None:
            return _denied(f"never: {blocked}")
        listed = None if args is None else await asyncio.to_thread(lists.denied, args, ctx.settings)
        return None if listed is None else _denied(f"deny list: {listed}")

    async def _resolve(
        self,
        raw_scopes: tuple[str, ...],
        reason: str,
        ctx: "TurnContext",
        args: Mapping[str, object] | None,
    ) -> _Outcome:
        try:
            scopes = parse_scopes(raw_scopes)
        except ScopeError as exc:
            return _denied(f"malformed scope: {exc}")
        if not scopes:
            return _granted("no scopes asked for", "none")
        refused = await self._refused(scopes, ctx, args)  # 1. in every mode
        if refused is not None:
            return refused
        safe = ctx.mode == "safe"
        sources = {scope.source for scope in scopes}
        if ctx.mode == "yolo" and (
            not self._settings.yolo_asks_first_touch
            or all(self._session.seen(source) for source in sources)
        ):  # 2. YOLO
            return _granted("auto-allowed: YOLO", "yolo")
        missing = tuple(s for s in scopes if not self._allowed(s, ctx.turn_id, safe))  # 3.
        if not missing:
            for scope in scopes:
                self._store.touch(scope)
            return _granted("existing grant", "grant")
        return await self._ask(missing, reason, ctx, safe)  # 4. one question for what is left

    async def _ask(
        self, missing: tuple[Scope, ...], reason: str, ctx: "TurnContext", safe: bool
    ) -> _Outcome:
        names = tuple(str(scope) for scope in missing)
        self._audit(ctx, names, "consent prompt", _Outcome("asking", reason, "ask"))
        answer = await self._answer(missing, reason, ctx, offer_always=not safe)
        outcome, commit = self._apply(answer, missing, ctx, safe)
        try:
            self._audit(ctx, names, "consent answer", outcome)
        except Exception:
            logger.exception("consent answer audit failed")
            return _denied("error: audit unavailable")  # nothing was granted: commit never ran
        commit()  # a grant changes only once its answer is on the record (I1)
        return outcome

    async def _answer(
        self, missing: tuple[Scope, ...], reason: str, ctx: "TurnContext", *, offer_always: bool
    ) -> AskAnswer:
        timeout = self._settings.ask_timeout_s
        try:
            async with asyncio.timeout(timeout):
                answer = await self._asker.ask(missing, reason, ctx, offer_always)
        except TimeoutError:
            return AskAnswer("timeout", "timeout")
        valid = isinstance(answer, AskAnswer) and answer.choice in _CHOICES
        return answer if valid else AskAnswer("no", "timeout")  # garbage is a no, never a yes

    def _apply(
        self, answer: AskAnswer, missing: tuple[Scope, ...], ctx: "TurnContext", safe: bool
    ) -> tuple[_Outcome, Callable[[], None]]:
        """The outcome of an answer, and the step that makes it so; the caller audits in between."""
        choice, method = answer.choice, answer.method
        if choice in ("no", "timeout"):
            return _denied("no" if choice == "no" else "no answer", method), _nothing
        if method not in _GRANT_METHODS:  # silence never grants, whatever the choice says
            return _denied(f"{choice} without an answer", method), _nothing
        if choice == "once" and ctx.turn_id == NO_TURN:  # nothing would ever end it (M1)
            return _denied("once outside a turn", method), _nothing
        grant_method = cast(GrantMethod, method)
        if choice == "never":
            return _denied("never", method), lambda: self._remember(missing, "never", grant_method)
        if choice == "always" and safe:
            choice = "session"  # Safe mode keeps no "always" (FR-CON-11)
        if choice == "always":
            return _granted(choice, method), lambda: self._remember(missing, "always", grant_method)
        held: Literal["once", "session"] = "once" if choice == "once" else "session"
        return _granted(choice, method), lambda: self._hold(missing, held, ctx)

    def _remember(
        self, missing: tuple[Scope, ...], lifetime: Lifetime, method: GrantMethod
    ) -> None:
        self._store.grant_all(missing, lifetime, method)  # one transaction: all scopes or none

    def _hold(
        self, missing: tuple[Scope, ...], lifetime: Literal["once", "session"], ctx: "TurnContext"
    ) -> None:
        for scope in missing:
            self._session.grant(scope, lifetime, ctx.turn_id)
