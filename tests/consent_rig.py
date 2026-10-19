"""A rig for consent tests: a scripted asker, a real store in tmp_path and a collected audit."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from jarvis.config import ConsentSettings
from jarvis.consent.broker import AskAnswer, Broker, Choice
from jarvis.consent.scope import Scope
from jarvis.consent.session import SessionGrants
from jarvis.consent.store import GrantStore
from jarvis.policy.decision import TurnContext
from jarvis.policy.model import Mode

TEAMS_R = "messages.teams:read"
TEAMS_W = "messages.teams:write"
MAIL_R = "email.outlook:read"


class ScriptedAsker:
    """Answers each question from a script (the last answer repeats) and records the questions."""

    def __init__(self, *answers: AskAnswer, delay_s: float = 0) -> None:
        self.answers = list(answers) or [AskAnswer("timeout", "timeout")]
        self.delay_s = delay_s
        self.asked: list[tuple[tuple[Scope, ...], str, bool]] = []

    async def ask(
        self, scopes: tuple[Scope, ...], reason: str, ctx: TurnContext, offer_always: bool
    ) -> AskAnswer:
        self.asked.append((scopes, reason, offer_always))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def says(
    choice: Choice, method: Literal["voice", "typed", "button", "key", "timeout"] = "voice"
) -> AskAnswer:
    return AskAnswer(choice, method)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Rig:
    store: GrantStore
    session: SessionGrants
    asker: ScriptedAsker
    broker: Broker
    clock: Clock
    audit: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def require(
        self,
        *scopes: str,
        mode: Mode = "balanced",
        turn: str = "t1",
        args: dict[str, object] | None = None,
    ) -> str:
        ctx = TurnContext(turn, mode=mode)
        return asyncio.run(self.broker.require(scopes, "to do that", ctx, args=args))

    def checks(self) -> list[dict[str, object]]:
        return [kw for msg, kw in self.audit if msg == "consent check"]


def make_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *answers: AskAnswer,
    settings: ConsentSettings | None = None,
    delay_s: float = 0,
) -> Rig:
    collected: list[tuple[str, dict[str, object]]] = []

    def record(source: str, message: str, **fields: object) -> None:
        collected.append((message, fields))

    monkeypatch.setattr("jarvis.consent.broker.audit", record)
    monkeypatch.setattr("jarvis.consent.store.audit", record)
    monkeypatch.setattr("jarvis.consent.session.audit", record)
    clock = Clock()
    store = GrantStore(tmp_path / "grants.json", clock=clock)
    session = SessionGrants()
    asker = ScriptedAsker(*answers, delay_s=delay_s)
    broker = Broker(store, session, asker, settings or ConsentSettings(), clock=clock)
    return Rig(store, session, asker, broker, clock, collected)
