"""FR-CON-13: managing consent by voice, on the fast path, through the gate."""

import asyncio
from pathlib import Path

import pytest

from jarvis.activity import ActivityLog
from jarvis.config import ConsentSettings, Settings
from jarvis.consent.broker import Broker, TurnAsker
from jarvis.consent.manage import Allow, ForgetAll, ListAccess, Revoke, parse, resolve, run
from jarvis.consent.scope import Scope
from jarvis.consent.session import SessionGrants
from jarvis.consent.store import GrantStore
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.turns import TurnRunner, TurnServices
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy.decision import TurnContext
from tests.fastpath_fakes import FakeDesktop
from tests.gated_rig import Confirmer
from tests.orchestrator_rig import FakeSpeaker, command


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Jarvis, what can you access?", ListAccess()),
        ("what do you have access to", ListAccess()),
        ("allow Teams", Allow("teams", always=False)),
        ("always allow my calendar", Allow("calendar", always=True)),
        ("allow my email always", Allow("email", always=True)),
        ("revoke Teams", Revoke("teams")),
        ("stop reading my email", Revoke("email")),
        ("forget all permissions", ForgetAll()),
        ("Jarvis, forget all permissions please", ForgetAll()),
        ("open Teams", None),
        ("allow", None),
    ],
)
def test_should_recognise_the_fr_con_13_phrases(text: str, intent: object) -> None:
    assert parse(text) == intent


@pytest.mark.parametrize(
    ("words", "sources"),
    [
        ("teams", ["messages.teams"]),
        ("email", ["email.gmail", "email.outlook"]),
        ("calendar", ["calendar.google", "calendar.outlook"]),
        ("documents", ["files.documents"]),
        ("the screen", ["screen"]),
        ("unicorns", []),
    ],
)
def test_should_resolve_a_spoken_source(words: str, sources: list[str]) -> None:
    assert resolve(words, ["files.documents"]) == sources


class World:
    def __init__(self, tmp_path: Path, *, confirm: bool = True, mode: str = "balanced") -> None:
        settings = ConsentSettings()
        self.store = GrantStore(tmp_path / "grants.json")
        self.broker = Broker(self.store, SessionGrants(), TurnAsker(settings), settings)
        self.confirmer = Confirmer(yes=confirm)
        self.mode = mode

    def say(self, text: str) -> tuple[str, str]:
        intent = parse(text)
        assert intent is not None
        ctx = TurnContext("t1", mode=self.mode, confirmer=self.confirmer)  # type: ignore[arg-type]
        final = asyncio.run(run(intent, self.broker, ctx))
        return final.status, final.spoken

    def stored(self) -> list[tuple[str, str]]:
        return [(str(g.scope), g.lifetime) for g in self.store.all()]


def test_should_say_when_nothing_is_allowed(tmp_path: Path) -> None:
    assert World(tmp_path).say("what can you access")[1].startswith("I don't have access")


def test_should_allow_for_the_session_without_asking_and_list_it(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.say("allow Teams") == (
        "success",
        "Okay, I can read your Teams messages for this session.",
    )
    assert world.confirmer.asked == [] and world.stored() == []  # held in memory only
    assert world.say("what can you access")[1] == (
        "For this session I can read your Teams messages."
    )


def test_should_confirm_always_on_the_card_then_store_it(tmp_path: Path) -> None:
    world = World(tmp_path)
    _, spoken = world.say("always allow my calendar")
    assert len(world.confirmer.asked) == 1  # FR-CON-13: visible, and confirmed
    assert world.stored() == [
        ("calendar.google:read", "always"),
        ("calendar.outlook:read", "always"),
    ]
    assert spoken.endswith("from now on.")


def test_should_store_nothing_when_always_is_not_confirmed(tmp_path: Path) -> None:
    world = World(tmp_path, confirm=False)
    assert world.say("always allow Teams")[0] == "cancelled"
    assert world.stored() == []


def test_should_let_the_users_own_words_replace_a_never(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.store.grant(Scope.parse("messages.teams:read"), "never", "voice")
    world.say("always allow Teams")
    assert world.stored() == [("messages.teams:read", "always")]


def test_should_revoke_and_say_what_it_stopped(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.say("always allow Teams")
    assert (
        world.say("stop reading my Teams")[1] == "Okay, I won't read your Teams messages any more."
    )
    assert world.stored() == []
    assert world.say("revoke Teams")[1] == "I had no access to that."


def test_should_forget_everything_never_included(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.store.grant(Scope.parse("email.gmail:read"), "never", "voice")
    world.say("allow Teams")
    world.say("forget all permissions")
    assert world.stored() == []
    assert world.say("what can you access")[1].startswith("I don't have access")


def test_should_say_when_it_does_not_know_the_source(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert "I don't know a source called unicorns" in world.say("allow unicorns")[1]


def test_should_ask_in_safe_mode_even_for_the_session(tmp_path: Path) -> None:
    world = World(tmp_path, mode="safe")
    world.say("allow Teams")
    assert len(world.confirmer.asked) == 1


def test_should_route_the_phrase_from_a_turn(tmp_path: Path) -> None:
    settings = ConsentSettings()
    broker = Broker(GrantStore(tmp_path / "g.json"), SessionGrants(), TurnAsker(settings), settings)
    speaker = FakeSpeaker()

    async def hud(event: object) -> None:
        return None

    services = TurnServices(
        settings=Settings(),
        mode="balanced",
        desktop=FakeDesktop([]),
        brain=None,
        voice=Voice(speaker, Timing(deaf_tail_s=0.0)),
        hud=hud,
        activity=ActivityLog(directory=tmp_path),
        timing=Timing(deaf_tail_s=0.0),
        windows=Windows(),
        trace=ToolTrace(),
        consent_admin=broker,
    )
    asyncio.run(TurnRunner(services).run(command("allow Teams", None)))
    assert speaker.said == ["Okay, I can read your Teams messages for this session."]
