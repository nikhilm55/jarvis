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

import time
from collections.abc import Callable
from typing import Literal

from jarvis.confirm.answers import HudAnswer, HudAnswers
from jarvis.confirm.exchange import Again, Exchange, Judged, Question
from jarvis.confirm.words import meaning, says_phrase
from jarvis.orchestrator.hud import HudSink
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy.decision import Kind
from jarvis.policy.ports import Answer

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
        self._exchange = Exchange(
            voice, windows, hud, answers, before_speaking=before_speaking, clock=clock
        )

    async def ask(
        self, prompt: str, kind: Kind, target_phrase: str | None = None, timeout_s: float = 15
    ) -> Answer:
        """Ask `prompt`; the answer, or a no by "timeout" when none came in `timeout_s`."""
        how = instruction(kind, target_phrase)

        def by_voice(text: str) -> Judged:
            verdict = judge(text, kind, target_phrase)
            return Again(instruction("click", None)) if verdict == "click" else _result(verdict)

        def by_hud(answer: HudAnswer) -> Judged:
            return _result(_judge_hud(answer, kind, target_phrase))

        question = Question(
            state="confirm",
            title=prompt,
            extra={"kind": kind, "phrase": target_phrase, "instruction": how},
            spoken=f"{prompt} {how}",
            voice=by_voice,
            hud=by_hud,
            reask=_reask(kind, target_phrase),
            no_answer=NO_ANSWER,
            timeout_s=timeout_s,
        )
        outcome = await self._exchange.run(question)
        return Answer(outcome.result == "yes", outcome.method)


def _result(verdict: _Verdict) -> Judged:
    return verdict if verdict in ("yes", "no") else None
