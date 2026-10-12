"""Fast-path matcher for whole-command voice commands."""

import re

from jarvis.fastpath.intents import (
    CloseApp,
    Intent,
    Mute,
    OpenApp,
    Stop,
    TellDate,
    TellTime,
    VolumeSet,
    VolumeStep,
)

# Precompiled regexes for normalisation.
_LEAD = re.compile(r"^(?:(?:can|could|would|will) you )?(?:please )?(?:, )?")
_TRAIL = re.compile(r"(?:(?: ,)* (?:please|thanks|thank you))*(?: ,)*$")
_CLAUSE_BREAK = re.compile(r"[,;:!?]|\.(?=\s)")
# ASCII and typographic punctuation only: letters (and combining marks) must survive intact,
# otherwise a non-Latin name would be silently mangled into a different one.
_PUNCT = re.compile('[!"$&()*/<=>@\\[\\]^`{|}~\u2018\u201c\u201d\u2013\u2014\u2026]')
_WHATS = re.compile(r"\bwhat'?s\b")
_TODAYS = re.compile(r"\btoday'?s\b")

# Precompiled fullmatch patterns for intents.
_STOP = re.compile(r"stop|cancel|shut up|never ?mind")
_MUTE = re.compile(r"(?P<un>un[- ]?)?mute(?: (?:the )?(?:sound|audio|volume))?")
_TIME = re.compile(
    r"(?:(?:what is|tell me|give me) (?:the )?(?:current )?time"
    r"|what time is it"
    r"|(?:the )?(?:current )?time)"
    r"(?: now| right now| currently)?"
)
_DATE = re.compile(
    r"(?:what is|tell me|give me) (?:the )?(?:today )?date(?: today)?"
    r"|today date"
    r"|what day is it(?: today)?"
    r"|what day is today"
    r"|what is today"
)
_STEP = re.compile(
    r"(?:(?:turn )?(?:the )?volume (?P<a>up|down)"
    r"|turn (?P<b>up|down) the volume"
    r"|(?P<c>raise|increase|lower|decrease|reduce) (?:the )?volume"
    r"|turn it (?P<d>up|down)"
    r"|(?:make it )?(?P<e>louder|quieter))"
)
_SET = re.compile(
    r"(?:(?:set|change|put|make) )?(?:the )?volume (?:to |at |of )?(?P<n>\d{1,3})(?: percent)?"
)
_APP = re.compile(r"(?P<verb>open|launch|start|run|close|quit|exit|kill) (?P<target>.+)")
_NAME_TOKEN = re.compile(r"[^\W_][\w+#-]*")

# Words that never belong in a plain app name: any of them means the command says more than
# "open/close <app>" (pronouns, chaining, other clauses, files, people) and goes to the brain.
_DENY = frozenset(
    """
    it its this that these those them him her he she they me my mine our your his their there
    here one ones some any all every everything other another both each same last previous next
    current new recent i we you yourself myself the a an
    and then also or but with without for from in on at to into onto of by about after before
    except until while if when so as than via near please thanks thank
    open launch start run close quit exit kill stop cancel play type search write send delete
    remove
    app application program file folder directory document window windows tab tabs page link url
    website site email message messages chat chats call meeting
    """.split()  # noqa: SIM905  (a word list reads better than a quoted list)
)

# "start"/"run" are also verbs for timers, recordings and scripts, so those targets go to the brain.
_DENY_START = frozenset(
    """
    timer stopwatch recording listening dictation dictating conversation meeting over again
    script test tests command routine
    """.split()  # noqa: SIM905  (a word list reads better than a quoted list)
)

_SIMPLE: tuple[tuple[re.Pattern[str], Intent], ...] = (
    (_STOP, Stop()),
    (_TIME, TellTime()),
    (_DATE, TellDate()),
)

_DIRECTION = {
    "up": 10,
    "raise": 10,
    "increase": 10,
    "louder": 10,
    "down": -10,
    "lower": -10,
    "decrease": -10,
    "reduce": -10,
    "quieter": -10,
}


def _normalise(command: str) -> str:
    """Lowercase, strip punctuation, and remove polite lead/trail phrases."""
    text = command.casefold().replace("\u2019", "'").replace("%", " percent ")
    text = _CLAUSE_BREAK.sub(" , ", text)
    text = _PUNCT.sub(" ", text)
    tokens: list[str] = []
    for raw in text.split():
        tok = raw if raw == "," else raw.rstrip(".-'").lstrip("'")
        if tok:
            tokens.append(tok)
    s = " ".join(tokens)
    s = _WHATS.sub("what is", s)
    s = _TODAYS.sub("today", s)
    s = _LEAD.sub("", s)
    s = _TRAIL.sub("", s)
    return s.strip()


def _match_simple(s: str) -> Intent | None:
    """Match the commands that carry no argument."""
    for pattern, intent in _SIMPLE:
        if pattern.fullmatch(s):
            return intent
    return None


def _match_mute(s: str) -> Intent | None:
    """Match a mute/unmute command."""
    m = _MUTE.fullmatch(s)
    return Mute(on=m.group("un") is None) if m else None


def _match_volume_step(s: str) -> Intent | None:
    """Match a relative volume change."""
    m = _STEP.fullmatch(s)
    if m:
        for group in ("a", "b", "c", "d", "e"):
            value = m.group(group)
            if value is not None:
                return VolumeStep(delta=_DIRECTION[value])
    return None


def _match_volume_set(s: str) -> Intent | None:
    """Match an absolute volume setting."""
    m = _SET.fullmatch(s)
    if m:
        n = int(m.group("n"))
        if n <= 100:
            return VolumeSet(percent=n)
    return None


def _app_name(target: str, verb: str) -> str | None:
    """Extract and validate the app name from the target phrase."""
    tokens = target.split()
    if tokens and tokens[0] == "up" and verb in {"open", "launch", "start", "run"}:
        tokens = tokens[1:]
    if tokens and tokens[0] in {"the", "a", "an"}:
        tokens = tokens[1:]
    if len(tokens) > 1 and tokens[-1] in {"app", "application"}:
        tokens = tokens[:-1]
    if not tokens or len(tokens) > 4:
        return None
    for tok in tokens:
        if not _NAME_TOKEN.fullmatch(tok):
            return None
        if tok in _DENY:
            return None
    if verb in {"start", "run"}:
        for tok in tokens:
            if tok in _DENY_START:
                return None
    return " ".join(tokens)


def _match_app(s: str) -> Intent | None:
    """Match an open/close app command."""
    m = _APP.fullmatch(s)
    if m:
        verb = m.group("verb")
        name = _app_name(m.group("target"), verb)
        if name is not None:
            if verb in {"open", "launch", "start", "run"}:
                return OpenApp(name=name)
            return CloseApp(name=name)
    return None


def match(command: str) -> Intent | None:
    """Return the intent for a whole-command pattern, or None unless certain (FR-NLU-02)."""
    if len(command) > 120:
        return None
    s = _normalise(command)
    if s == "":
        return None
    for handler in (
        _match_simple,
        _match_mute,
        _match_volume_step,
        _match_volume_set,
        _match_app,
    ):
        result = handler(s)
        if result is not None:
            return result
    return None
