"""One spoken question with a HUD card: the first acceptable answer wins (FR-SAFE-07, FR-CON-06).

Used by confirmations and consent questions alike. An answer is spoken inside the reply window
with no wake word, or comes from the card: a button, a key or the typed box. The question's
judges say what each answer means: a result, `Again(text)` (say this and keep waiting), or
None (unclear). Unclear is asked again once, then ends the question; no answer before the
deadline ends it too, and the caller's line for that is said once.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.confirm.answers import HudAnswer, HudAnswers
from jarvis.orchestrator.hud import HudEvent, HudSink, HudState
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy.ports import Method

__all__ = ["Again", "Exchange", "Judged", "Outcome"]


@dataclass(frozen=True)
class Again:
    """Not an answer this question takes: say `text` and keep waiting (not a re-ask)."""

    text: str


Judged = str | Again | None


@dataclass(frozen=True)
class Outcome:
    """How a question ended: `result` is None when unclear twice or unanswered."""

    result: str | None
    method: Method


@dataclass(frozen=True)
class Question:
    """What to show and say, and how to read the answers."""

    state: HudState
    title: str
    extra: dict[str, object]
    spoken: str
    voice: Callable[[str], Judged]
    hud: Callable[[HudAnswer], Judged]
    reask: str
    no_answer: str
    timeout_s: float


class Exchange:
    """Runs one question at a time through the voice and the HUD."""

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

    async def run(self, question: Question) -> Outcome:
        """Show the card, say the question, and return the first acceptable answer."""
        await self._hud(HudEvent(question.state, question.title, question.extra))
        from_hud = self._answers.open()
        try:
            await self.say(question.spoken)
            return await self._wait(from_hud, question)
        finally:
            self._answers.close(from_hud)
            await self._hud(HudEvent(question.state, "", {"closed": True}))

    async def _wait(self, from_hud: asyncio.Future[HudAnswer], question: Question) -> Outcome:
        deadline = self._clock() + question.timeout_s
        asked_again = False
        method: Method = "timeout"
        while (remaining := deadline - self._clock()) > 0:
            judged: Judged
            if from_hud.done():
                answer = None if from_hud.cancelled() else from_hud.result()
                if answer is None:
                    break
                judged, method = question.hud(answer), answer.method
                if judged is None or isinstance(judged, Again):
                    from_hud = self._answers.open()  # not an answer this question takes
                    continue
            else:
                heard = await self._listen(from_hud, remaining)
                if heard is None:
                    continue  # the HUD answered, or the window ran out: the loop decides
                judged, method = question.voice(heard), "voice"
            if isinstance(judged, str):
                return Outcome(judged, method)
            if isinstance(judged, Again):
                await self.say(judged.text)
            elif not asked_again:
                asked_again = True
                await self.say(question.reask)
            else:
                return Outcome(None, method)  # unclear twice
        await self.say(question.no_answer)
        return Outcome(None, "timeout")

    async def _listen(self, from_hud: asyncio.Future[HudAnswer], seconds: float) -> str | None:
        """A spoken answer in the reply window; None when the HUD answered or time ran out."""
        await self._hud(HudEvent("listening", "Reply...", {"window": "reply"}))
        spoken = asyncio.ensure_future(self._windows.ask(seconds))
        pending: set[asyncio.Future[object]] = {spoken, from_hud}  # type: ignore[arg-type]
        await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        if not spoken.done():
            self._windows.close()  # resolves the window with no answer
        return await spoken

    async def say(self, text: str) -> None:
        """Speak `text` (cutting the thinking earcon first) and wait until it is said."""
        self._before_speaking()
        await self._hud(HudEvent("speaking", text))
        await self._voice.wait(self._voice.say(text))
