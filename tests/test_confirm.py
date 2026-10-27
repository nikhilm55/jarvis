"""The Confirmer (FR-SAFE-07, FR-SAFE-02): voice and HUD answers, re-ask, timeout, kinds."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from jarvis.activity import ActivityLog
from jarvis.config import Settings
from jarvis.confirm import NO_ANSWER, Confirmer, HudAnswer, HudAnswers
from jarvis.confirm.words import meaning, says_phrase
from jarvis.fastpath.intents import VolumeSet
from jarvis.orchestrator.hud import HudEvent
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.turns import TurnRunner, TurnServices
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy.decision import Kind
from jarvis.policy.ports import Answer
from tests.fastpath_fakes import FakeDesktop
from tests.orchestrator_rig import FakeSpeaker, command, until

# --- what an answer means -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yes", "yes"),
        ("Yes.", "yes"),
        ("Jarvis, confirm", "yes"),
        ("do it", "yes"),
        ("Go ahead please", "yes"),
        ("send it", "yes"),
        ("no", "no"),
        ("No thanks", "no"),
        ("cancel", "no"),
        ("yes no", None),
        ("maybe", None),
        ("yesterday", None),
        ("", None),
        ("do it later", None),
    ],
)
def test_should_read_only_the_fr_safe_07_words_as_an_answer(text: str, expected: str) -> None:
    assert meaning(text) == expected


@pytest.mark.parametrize(
    ("text", "phrase", "expected"),
    [
        ("confirm rm downloads a dot txt", "confirm rm ~/Downloads/a.txt", True),
        ("Confirm RM ~/Downloads/a.txt", "confirm rm ~/Downloads/a.txt", True),
        ("Jarvis, confirm delete", "confirm delete", True),
        ("confirm", "confirm rm ~/Downloads/a.txt", False),
        ("yes", "confirm delete", False),
        ("rm downloads a txt", "confirm rm ~/Downloads/a.txt", False),
        ("confirm rm downloads", "confirm rm ~/Downloads/a.txt", False),
        ("confirm", "confirm", True),
    ],
)
def test_should_need_confirm_and_the_target_for_the_guardrail(
    text: str, phrase: str, expected: bool
) -> None:
    assert says_phrase(text, phrase) is expected


# --- the Confirmer ------------------------------------------------------------------------------


class Rig:
    """A Confirmer over the real reply window and Voice, with a fake speaker and HUD."""

    def __init__(self) -> None:
        self.speaker = FakeSpeaker()
        self.windows = Windows()
        self.answers = HudAnswers()
        self.events: list[HudEvent] = []
        self.spoke_first = 0
        self.confirmer = Confirmer(
            Voice(self.speaker, Timing(deaf_tail_s=0.0)),
            self.windows,
            self._hud,
            self.answers,
            before_speaking=self._before,
        )

    async def _hud(self, event: HudEvent) -> None:
        self.events.append(event)

    def _before(self) -> None:
        self.spoke_first += 1

    async def reply_window(self) -> None:
        await until(lambda: self.windows.kind == "reply")


Script = Callable[[Rig], Awaitable[None]]


def ask(
    script: Script, kind: Kind = "voice", phrase: str | None = None, timeout_s: float = 2.0
) -> tuple[Answer, Rig]:
    async def main() -> tuple[Answer, Rig]:
        rig = Rig()
        asking = asyncio.create_task(rig.confirmer.ask("Close Firefox?", kind, phrase, timeout_s))
        await script(rig)
        return await asyncio.wait_for(asking, 5), rig

    return asyncio.run(main())


def say(*texts: str) -> Script:
    async def script(rig: Rig) -> None:
        for text in texts:
            await rig.reply_window()
            assert rig.windows.offer_answer(text)
            await asyncio.sleep(0)

    return script


def hud(*answers: HudAnswer) -> Script:
    async def script(rig: Rig) -> None:
        for answer in answers:
            await until(lambda: rig.answers.waiting)
            assert rig.answers.post(answer)
            await asyncio.sleep(0)

    return script


def then(*scripts: Script) -> Script:
    async def script(rig: Rig) -> None:
        for step in scripts:
            await step(rig)

    return script


def test_should_speak_the_question_with_how_to_answer_and_take_a_spoken_yes() -> None:
    answer, rig = ask(say("yes"))
    assert answer == Answer(True, "voice")
    assert rig.speaker.said == ["Close Firefox? Say yes or no."]
    assert rig.spoke_first >= 1  # the thinking earcon is cut before the question


def test_should_take_a_spoken_no() -> None:
    assert ask(say("cancel"))[0] == Answer(False, "voice")


def test_should_ask_again_once_after_an_unclear_answer() -> None:
    answer, rig = ask(say("what?", "do it"))
    assert answer == Answer(True, "voice")
    assert rig.speaker.said[1:] == ["Sorry, please say yes or no."]


def test_should_count_two_unclear_answers_as_no() -> None:
    answer, rig = ask(say("what?", "hmm"))
    assert answer == Answer(False, "voice")
    assert len(rig.speaker.said) == 2  # the question and one re-ask, nothing more


def test_should_say_once_that_no_answer_is_a_no() -> None:
    async def silent(rig: Rig) -> None:
        return None

    answer, rig = ask(silent, timeout_s=0.05)
    assert answer == Answer(False, "timeout")
    assert rig.speaker.said.count(NO_ANSWER) == 1
    assert rig.windows.kind is None


@pytest.mark.parametrize("method", ["button", "key", "typed"])
def test_should_take_a_yes_from_the_hud_and_close_the_reply_window(method: str) -> None:
    answer, rig = ask(hud(HudAnswer("yes", method)))  # type: ignore[arg-type]
    assert answer == Answer(True, method)  # type: ignore[arg-type]
    assert rig.windows.kind is None
    assert not rig.answers.waiting


def test_should_show_the_card_then_take_it_down() -> None:
    _, rig = ask(say("yes"), kind="guardrail", phrase="confirm delete")
    cards = [e for e in rig.events if e.state == "confirm"]
    assert cards[0].text == "Close Firefox?"
    assert cards[0].extra["kind"] == "guardrail"
    assert cards[0].extra["phrase"] == "confirm delete"
    assert cards[-1].extra == {"closed": True}


def test_should_refuse_a_late_hud_answer_after_the_question_closed() -> None:
    _, rig = ask(say("no"))
    assert rig.answers.post(HudAnswer("yes", "button")) is False


# T3 in Safe and Balanced: only a click confirms (plan 2d).


def test_should_tell_a_spoken_yes_to_click_and_keep_waiting() -> None:
    answer, rig = ask(then(say("yes"), hud(HudAnswer("yes", "button"))), kind="click")
    assert answer == Answer(True, "button")
    assert rig.speaker.said[1] == "Click Confirm on the screen to go ahead, or say no."


@pytest.mark.parametrize(
    "answer", [HudAnswer("yes", "key"), HudAnswer("yes", "typed"), HudAnswer("confirm", "typed")]
)
def test_should_not_take_a_key_or_typed_yes_for_a_click(answer: HudAnswer) -> None:
    result, _ = ask(hud(answer), kind="click", timeout_s=0.3)
    assert result == Answer(False, "timeout")


def test_should_take_a_spoken_no_for_a_click() -> None:
    assert ask(say("no"), kind="click")[0] == Answer(False, "voice")


# YOLO T3: say "confirm" and the target (FR-SAFE-02).

PHRASE = "confirm rm ~/Downloads/a.txt"


def test_should_ask_for_the_phrase_and_take_it_spoken() -> None:
    answer, rig = ask(say("confirm rm downloads a txt"), kind="guardrail", phrase=PHRASE)
    assert answer == Answer(True, "voice")
    assert rig.speaker.said[0] == f"Close Firefox? To go ahead, say '{PHRASE}'."


def test_should_not_take_a_bare_yes_for_the_guardrail() -> None:
    answer, rig = ask(say("yes", "yes"), kind="guardrail", phrase=PHRASE)
    assert answer == Answer(False, "voice")
    assert rig.speaker.said[1] == f"Sorry, I need you to say '{PHRASE}', or no."


def test_should_take_the_phrase_typed_but_not_a_button_for_the_guardrail() -> None:
    script = hud(HudAnswer("yes", "button"), HudAnswer(PHRASE, "typed"))
    assert ask(script, kind="guardrail", phrase=PHRASE)[0] == Answer(True, "typed")


@pytest.mark.parametrize("kind", ["voice", "click", "guardrail"])
def test_should_take_a_no_button_for_every_kind(kind: Kind) -> None:
    assert ask(hud(HudAnswer("no", "button")), kind=kind, phrase=PHRASE)[0] == Answer(
        False, "button"
    )


# --- the turn asks through it (wiring) ----------------------------------------------------------


def _safe_runner(
    tmp_path: Path, answers: HudAnswers | None
) -> tuple[TurnRunner, list[str], Windows]:
    events: list[str] = []
    windows = Windows()

    async def no_hud(event: HudEvent) -> None:
        return None

    services = TurnServices(
        settings=Settings(),
        mode="safe",
        desktop=FakeDesktop(events),
        brain=None,
        voice=Voice(FakeSpeaker(), Timing(deaf_tail_s=0.0)),
        hud=no_hud,
        activity=ActivityLog(directory=tmp_path),
        timing=Timing(deaf_tail_s=0.0),
        windows=windows,
        trace=ToolTrace(),
        answers=answers,
    )
    return TurnRunner(services), events, windows


@pytest.mark.parametrize(("reply", "ran"), [("yes", True), ("no", False)])
def test_should_ask_before_a_safe_mode_volume_change_and_obey_the_answer(
    tmp_path: Path, reply: str, ran: bool
) -> None:
    async def main() -> list[str]:
        runner, events, windows = _safe_runner(tmp_path, HudAnswers())
        turn = asyncio.create_task(runner.run(command("set volume to 30", VolumeSet(30))))
        await until(lambda: windows.kind == "reply")
        windows.offer_answer(reply)
        await asyncio.wait_for(turn, 5)
        return events

    assert (asyncio.run(main()) == ["desktop.volume_set"]) is ran


def test_should_refuse_without_asking_when_no_hud_answers_are_wired(tmp_path: Path) -> None:
    async def main() -> tuple[list[str], Windows]:
        runner, events, windows = _safe_runner(tmp_path, None)
        await asyncio.wait_for(runner.run(command("set volume to 30", VolumeSet(30))), 5)
        return events, windows

    events, windows = asyncio.run(main())
    assert events == []
    assert windows.kind is None  # nothing was asked
