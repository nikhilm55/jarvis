"""The consent question (FR-CON-04..07, 15) and the card that goes with it (FR-CON-06)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from jarvis.config import ConsentSettings
from jarvis.confirm import HudAnswer, HudAnswers
from jarvis.confirm.consent_question import LEAVE_IT, ConsentQuestion, choice_of
from jarvis.consent.broker import Broker, TurnAsker
from jarvis.consent.session import SessionGrants
from jarvis.consent.store import GrantStore
from jarvis.consent.wording import badge, describe
from jarvis.orchestrator.hud import HudEvent
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy.decision import TurnContext
from tests.orchestrator_rig import FakeSpeaker, until
from tests.test_hud_confirm import _card_logic

TEAMS_R, TEAMS_W, CAL_R = "messages.teams:read", "messages.teams:write", "calendar.google:read"

# --- the words (FR-CON-04) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scopes", "said"),
    [
        ((TEAMS_R,), "read your Teams messages"),
        ((TEAMS_W,), "send your Teams messages"),
        ((TEAMS_R, TEAMS_W), "read and send your Teams messages"),  # never bundled silently
        (("files.documents:write",), "change files in your Documents folder"),
        (("screen:read",), "see your screen"),
        ((TEAMS_R, CAL_R), "see your Google calendar and read your Teams messages"),
        (("contacts.m365:read",), "look up your Microsoft 365 contacts"),
        (("widgets.acme:read",), "read your Acme widgets"),
        (("gadgets:write",), "change your gadgets"),
    ],
)
def test_should_say_what_and_where_in_plain_words(scopes: tuple[str, ...], said: str) -> None:
    assert describe(scopes) == said


def test_should_badge_one_source_by_category_and_app() -> None:
    assert badge((TEAMS_R, TEAMS_W)) == "messages · Teams"
    assert badge((TEAMS_R, CAL_R)) == "2 sources"
    assert badge(("screen:read",)) == "screen"


@pytest.mark.parametrize(
    ("text", "choice"),
    [
        ("yes", "once"),
        ("Allow", "once"),
        ("yes for now", "session"),
        ("for this session", "session"),
        ("Yes always", "always"),
        ("always allow", "always"),
        ("no", "no"),
        ("deny", "no"),
        ("never", "never"),
        ("Don't ever ask", "never"),
        ("maybe later", None),
        ("yes no", None),
    ],
)
def test_should_read_the_fr_con_05_answers(text: str, choice: str | None) -> None:
    assert choice_of(text) == choice


# --- asking --------------------------------------------------------------------------------------


class Rig:
    def __init__(self) -> None:
        self.speaker = FakeSpeaker()
        self.windows = Windows()
        self.answers = HudAnswers()
        self.events: list[HudEvent] = []
        self.told: set[str] = set()
        self.question = ConsentQuestion(
            Voice(self.speaker, Timing(deaf_tail_s=0.0)),
            self.windows,
            self._hud,
            self.answers,
            told_cloud=self.told,
        )

    async def _hud(self, event: HudEvent) -> None:
        self.events.append(event)


Script = Callable[[Rig], Awaitable[None]]


def say(*texts: str) -> Script:
    async def script(rig: Rig) -> None:
        for text in texts:
            await until(lambda: rig.windows.kind == "reply")
            assert rig.windows.offer_answer(text)
            await asyncio.sleep(0)

    return script


def press(*answers: HudAnswer) -> Script:
    async def script(rig: Rig) -> None:
        for answer in answers:
            await until(lambda: rig.answers.waiting)
            assert rig.answers.post(answer)
            await asyncio.sleep(0)

    return script


def ask(
    script: Script,
    scopes: tuple[str, ...] = (TEAMS_R,),
    *,
    reason: str = "read your unread messages",
    offer_always: bool = True,
    timeout_s: float = 2.0,
    rig: Rig | None = None,
) -> tuple[tuple[str, str], Rig]:
    async def main() -> tuple[tuple[str, str], Rig]:
        the_rig = rig or Rig()
        asking = asyncio.create_task(the_rig.question.ask(scopes, reason, offer_always, timeout_s))
        await script(the_rig)
        return await asyncio.wait_for(asking, 5), the_rig

    return asyncio.run(main())


def test_should_ask_in_the_fr_con_04_words_and_name_the_cloud_once() -> None:
    answer, rig = ask(say("yes"))
    assert answer == ("once", "voice")
    assert rig.speaker.said == [
        "To read your unread messages, I need to read your Teams messages. "
        "Do I have your permission? This sends it to Claude, in the cloud. "
        "You can say yes, yes always, or no."
    ]
    _, rig = ask(say("no"), rig=rig)
    assert "cloud" not in rig.speaker.said[-1]  # FR-CON-15: the first time only


def test_should_say_to_do_that_when_the_gate_asks() -> None:
    _, rig = ask(say("yes"), reason="")
    assert rig.speaker.said[0].startswith("To do that I need to read your Teams messages.")


def test_should_offer_no_always_in_safe_mode() -> None:
    _, rig = ask(say("no"), offer_always=False)
    assert rig.speaker.said[0].endswith("Say yes or no.")
    [card] = [e for e in rig.events if e.state == "consent" and not e.extra.get("closed")]
    assert card.extra["offer_always"] is False and card.extra["badge"] == "messages · Teams"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (HudAnswer("a", "key"), ("always", "key")),
        (HudAnswer("s", "key"), ("session", "key")),
        (HudAnswer("session", "button"), ("session", "button")),
        (HudAnswer("never", "typed"), ("never", "typed")),
        (HudAnswer("no", "button"), ("no", "button")),
    ],
)
def test_should_take_the_card_buttons_keys_and_typing(
    answer: HudAnswer, expected: tuple[str, str]
) -> None:
    assert ask(press(answer))[0] == expected


def test_should_not_take_a_lone_spoken_letter() -> None:
    answer, rig = ask(say("a", "a"))
    assert answer == ("no", "voice")  # unclear twice
    assert rig.speaker.said[1] == "Sorry, say yes, yes always, or no."


def test_should_count_silence_as_no_and_say_so_once() -> None:
    async def silent(rig: Rig) -> None:
        return None

    answer, rig = ask(silent, timeout_s=0.05)
    assert answer == ("timeout", "timeout")
    assert rig.speaker.said.count(LEAVE_IT) == 1


# --- through the real broker ---------------------------------------------------------------------


@pytest.mark.parametrize(("reply", "result"), [("yes always", "granted"), ("no", "denied")])
def test_should_ask_through_the_turn_and_store_the_answer(
    tmp_path: Path, reply: str, result: str
) -> None:
    settings = ConsentSettings(ask_timeout_s=2)
    store = GrantStore(tmp_path / "grants.json")
    broker = Broker(store, SessionGrants(), TurnAsker(settings), settings)

    async def main() -> tuple[str, Rig]:
        rig = Rig()
        ctx = TurnContext("t1", mode="balanced", consent_question=rig.question)
        asking = asyncio.create_task(broker.require((TEAMS_R,), "", ctx))
        await say(reply)(rig)
        return await asyncio.wait_for(asking, 5), rig

    got, _ = asyncio.run(main())
    assert got == result
    held = [(str(g.scope), g.lifetime) for g in store.all()]
    assert held == ([(TEAMS_R, "always")] if result == "granted" else [])


def test_should_deny_without_asking_when_the_turn_has_no_question(tmp_path: Path) -> None:
    settings = ConsentSettings()
    broker = Broker(GrantStore(tmp_path / "g.json"), SessionGrants(), TurnAsker(settings), settings)
    ctx = TurnContext("t1", mode="balanced")
    assert asyncio.run(broker.require((TEAMS_R,), "", ctx)) == "denied"


# --- the card (page logic under node) ------------------------------------------------------------


def test_should_show_four_answers_and_ysan_on_the_consent_card() -> None:
    extra = {"kind": "consent", "badge": "messages · Teams", "body": "x", "cloud": "Claude (cloud)"}
    model = _card_logic(f"cardModel({json.dumps(extra)})")
    assert [b["answer"] for b in model["buttons"]] == ["once", "session", "always", "no"]
    assert (
        model["keys"] == ["Y", "S", "A", "N"] and model["cloud"] == "Data goes to: Claude (cloud)"
    )
    safe = _card_logic(f"cardModel({json.dumps({**extra, 'offer_always': False})})")
    assert [b["answer"] for b in safe["buttons"]] == ["once", "session", "no"]
    assert safe["keys"] == ["Y", "S", "N"]


@pytest.mark.parametrize(
    ("key", "offer_always", "expected"),
    [
        ("y", True, "y"),
        ("S", True, "s"),
        ("a", True, "a"),
        ("a", False, None),
        ("Escape", True, "n"),
    ],
)
def test_should_map_ysan_keys_for_consent(
    key: str, offer_always: bool, expected: str | None
) -> None:
    js = f"keyAnswer({json.dumps(key)}, 'consent', {json.dumps(offer_always)})"
    assert _card_logic(js) == expected
