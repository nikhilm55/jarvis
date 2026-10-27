"""The consent question, spoken and on the HUD card (FR-CON-04..07, 15).

"To read your unread messages I need to read your Teams messages. Do I have your permission?
You can say yes, yes always, or no." The card offers Allow once, This session, Always (not in
Safe mode, FR-CON-11) and Deny, with the keys Y, S, A and N and a typed box. The first time a
source's data would go to the cloud brain, the question says so (FR-CON-15).
"""

import time
from collections.abc import Callable

from jarvis.confirm.answers import HudAnswer, HudAnswers
from jarvis.confirm.exchange import Exchange, Judged, Question
from jarvis.confirm.words import words
from jarvis.consent.wording import badge, describe
from jarvis.orchestrator.hud import HudSink
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows

__all__ = ["LEAVE_IT", "ConsentQuestion", "choice_of"]

LEAVE_IT = "I'll leave that for now."  # FR-CON-07: no answer is a no, said once
CLOUD = "Claude (cloud)"

# FR-CON-05's answers; buttons send the first word of each, keys send y / s / a / n.
_CHOICES: dict[str, tuple[str, ...]] = {
    "once": ("yes", "y", "allow", "allow once", "once", "yes once", "just this once"),
    "session": (
        "s",
        "session",
        "this session",
        "for this session",
        "yes for this session",
        "allow for this session",
        "for now",
        "yes for now",
    ),
    "always": ("a", "always", "yes always", "always allow", "allow always"),
    "no": ("n", "no", "deny", "not now", "cancel", "no thanks"),
    "never": ("never", "never allow", "don t ever ask", "do not ever ask", "dont ever ask"),
}


def choice_of(text: str) -> str | None:
    """once / session / always / no / never for FR-CON-05's words, else None (unclear)."""
    said = " ".join(words(text))
    return next((choice for choice, said_as in _CHOICES.items() if said in said_as), None)


class ConsentQuestion:
    """Asks one consent question at a time; remembers which sources heard the cloud note."""

    def __init__(  # noqa: PLR0913 - the ports, plus test seams
        self,
        voice: Voice,
        windows: Windows,
        hud: HudSink,
        answers: HudAnswers,
        *,
        told_cloud: set[str] | None = None,
        before_speaking: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`told_cloud` is shared across turns: the sources already told about the cloud."""
        self._exchange = Exchange(
            voice, windows, hud, answers, before_speaking=before_speaking, clock=clock
        )
        self._told_cloud = told_cloud if told_cloud is not None else set()

    async def ask(
        self, scopes: tuple[str, ...], reason: str, offer_always: bool, timeout_s: float = 15
    ) -> tuple[str, str]:
        """(choice, method): once / session / always / no / never, or ("timeout", "timeout")."""
        what = describe(scopes)
        lead = (
            f"To {reason.strip().rstrip('.')}, I need to {what}."
            if reason.strip()
            else (f"To do that I need to {what}.")
        )
        sources = {scope.partition(":")[0] for scope in scopes}
        cloud = "" if sources <= self._told_cloud else " This sends it to Claude, in the cloud."
        self._told_cloud |= sources
        options = "You can say yes, yes always, or no." if offer_always else "Say yes or no."
        spoken = f"{lead} Do I have your permission?{cloud} {options}"

        def by_voice(text: str) -> Judged:
            if len(" ".join(words(text))) <= 1:
                return None  # a lone letter is a key, never speech (noise can sound like "a")
            return choice_of(text)

        def by_hud(answer: HudAnswer) -> Judged:
            return choice_of(answer.text)

        question = Question(
            state="consent",
            title="Permission needed",
            extra={
                "kind": "consent",
                "badge": badge(scopes),
                "body": lead,
                "cloud": CLOUD,
                "offer_always": offer_always,
            },
            spoken=spoken,
            voice=by_voice,
            hud=by_hud,
            reask="Sorry, say yes, yes always, or no." if offer_always else "Sorry, yes or no?",
            no_answer=LEAVE_IT,
            timeout_s=timeout_s,
        )
        outcome = await self._exchange.run(question)
        if outcome.result is None:
            return ("timeout", "timeout") if outcome.method == "timeout" else ("no", outcome.method)
        return outcome.result, outcome.method
