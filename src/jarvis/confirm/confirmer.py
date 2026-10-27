"""The real `Confirmer`: speak the question, take the first acceptable answer (FR-SAFE-07).

An answer can be spoken inside the reply window with no wake word, or come from the HUD:
its buttons, the `Y`/`N` keys or the typed box. What counts as a yes depends on the kind:

- `voice`: any of FR-SAFE-07's yes words, by voice, button, key or typing.
- `click`: only the HUD's Confirm button (T3 in Safe and Balanced, plan 2d); a spoken yes is
  told to click.
- `guardrail`: "confirm" plus the target, spoken or typed (FR-SAFE-02); a bare yes is not enough.

A no is a no from any channel. An unclear answer is asked again once, then counts as no; no
answer before the deadline is a no, said once (FR-SAFE-07, plan 2a-c).
"""

import asyncio
import time
from collections.abc import Callable
from typing import Literal

from jarvis.confirm.answers import HudAnswer, HudAnswers
from jarvis.confirm.words import meaning, says_phrase
from jarvis.orchestrator.hud import HudEvent, HudSink
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy.decision import Kind
from jarvis.policy.ports import Answer, Method

__all__ = ["NO_ANSWER", "Confirmer"]

NO_ANSWER = "No answer, so I won't do it."
_Verdict = Literal["yes", "no", "unclear", "click"]


def instruction(kind: Kind, phrase: str | None) -> str:
    """How to answer, said after the question."""
    if kind == "click":
        return "Click Confirm on the screen to go ahead, or say no."
    if kind == "guardrail":
        return f"To go ahead, say '{phrase or 'confirm'}'."
    return "Say yes or no."


def _reask(kind: Kind, phrase: str | None) -> str:
    if kind == "guardrail":
        return f"Sorry, I need you to say '{phrase or 'confirm'}', or no."
    return "Sorry, please say yes or no."


def judge(text: str, kind: Kind, phrase: str | None) -> _Verdict:
    """What a spoken or typed answer means for a question of `kind`."""
    said = meaning(text)
    if said == "no":
        return "no"
    if kind == "guardrail":
        return "yes" if says_phrase(text, phrase or "confirm") else "unclear"
    if said == "yes":
        return "click" if kind == "click" else "yes"
    return "unclear"


def _judge_hud(answer: HudAnswer, kind: Kind, phrase: str | None) -> _Verdict:
    if answer.method == "typed":
        verdict = judge(answer.text, kind, phrase)
        return "unclear" if verdict == "click" else verdict
    said = meaning(answer.text)
    if said == "no":
        return "no"
    if said == "yes" and (kind == "voice" or (kind == "click" and answer.method == "button")):
        return "yes"
    return "unclear"  # a key for a click, or a button for the spoken guardrail


class Confirmer:
    """Asks one confirmation at a time through the voice and the HUD."""

    def __init__(  # noqa: PLR0913 - the ports, plus test seams
        self,
        voice: Voice,
        windows: Windows,
        hud: HudSink,
        answers: HudAnswers,
        *,
        before_speaking: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the voice, the reply window, the HUD and its answer channel."""
        self._voice = voice
        self._windows = windows
        self._hud = hud
        self._answers = answers
        self._before_speaking = before_speaking
        self._clock = clock

    async def ask(
        self, prompt: str, kind: Kind, target_phrase: str | None = None, timeout_s: float = 15
    ) -> Answer:
        """Ask `prompt`; the answer, or a no by "timeout" when none came in `timeout_s`."""
        how = instruction(kind, target_phrase)
        extra: dict[str, object] = {"kind": kind, "phrase": target_phrase, "instruction": how}
        await self._hud(HudEvent("confirm", prompt, extra))
        from_hud = self._answers.open()
        try:
            await self._say(f"{prompt} {how}")
            return await self._wait(from_hud, kind, target_phrase, timeout_s)
        finally:
            self._answers.close(from_hud)
            await self._hud(HudEvent("confirm", "", {"closed": True}))

    async def _wait(
        self,
        from_hud: asyncio.Future[HudAnswer],
        kind: Kind,
        phrase: str | None,
        timeout_s: float,
    ) -> Answer:
        deadline = self._clock() + timeout_s
        asked_again = False
        method: Method = "timeout"
        while (remaining := deadline - self._clock()) > 0:
            if from_hud.done():
                answer = None if from_hud.cancelled() else from_hud.result()
                if answer is None:
                    break
                verdict = _judge_hud(answer, kind, phrase)
                method = answer.method
                if verdict == "unclear":
                    from_hud = self._answers.open()  # not an answer this question takes
                    continue
            else:
                heard = await self._listen(from_hud, remaining)
                if heard is None:
                    continue  # the HUD answered, or the window ran out: the loop decides
                verdict, method = judge(heard, kind, phrase), "voice"
            if verdict in ("yes", "no"):
                return Answer(verdict == "yes", method)
            if verdict == "click":
                await self._say(instruction("click", None))
            elif not asked_again:
                asked_again = True
                await self._say(_reask(kind, phrase))
            else:
                return Answer(False, method)  # unclear twice is a no
        await self._say(NO_ANSWER)
        return Answer(False, "timeout")

    async def _listen(self, from_hud: asyncio.Future[HudAnswer], seconds: float) -> str | None:
        """A spoken answer in the reply window; None when the HUD answered or time ran out."""
        await self._hud(HudEvent("listening", "Reply...", {"window": "reply"}))
        spoken = asyncio.ensure_future(self._windows.ask(seconds))
        pending: set[asyncio.Future[object]] = {spoken, from_hud}  # type: ignore[arg-type]
        await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        if not spoken.done():
            self._windows.close()  # resolves the window with no answer
        return await spoken

    async def _say(self, text: str) -> None:
        self._before_speaking()
        await self._hud(HudEvent("speaking", text))
        await self._voice.wait(self._voice.say(text))
