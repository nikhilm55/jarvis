"""First-word gate (FR-ACT-04/06) ported from the M0a spike (table D).

After STT, it checks the transcript's first word and strips the wake word to
get the command. It does NOT apply the detector threshold
(Settings.wake.threshold) or the >= 400 ms silence rule: the orchestrator
combines those with the gate (FR-ACT-05). An accepted "Jarvis" alone gives an
empty command; handling that (FR-ACT-07) is the orchestrator's job.
"""

import re
from dataclasses import dataclass

VARIANTS: frozenset[str] = frozenset({"jarvis", "jervis", "jarvas", "jarviss", "jarvi", "javis"})
REAL_WORDS: frozenset[str] = frozenset(
    {
        "service",
        "harvest",
        "nervous",
        "travis",
        "davis",
        "elvis",
        "garvey",
        "jars",
        "jar",
        "charts",
        "tardis",
        "darts",
        "jobs",
        "java",
        "jeremy",
        "harvey",
        "marvin",
        "mavis",
        "parvis",
    }
)
FILLERS: frozenset[str] = frozenset({"um", "uh", "er", "erm", "hmm", "ah", "okay", "ok", "so"})
MAX_EDITS = 2
WAKE_WORD = "jarvis"

_FIRST_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*")
_SEP_RE = re.compile(r"^[\s,.:;!?\u2026\-\u2013\u2014]+")
_FILLER_RE = re.compile(r"^([A-Za-z]+)(?![A-Za-z'\u2019\-])", re.IGNORECASE)


def levenshtein(a: str, b: str) -> int:
    """Classic single-row Levenshtein distance."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


@dataclass(frozen=True)
class GateResult:
    """Outcome of the first-word gate."""

    accepted: bool
    command: str
    first_word: str


def _strip_fillers(rest: str) -> str:
    """Drop leading separators and filler words from rest."""
    while True:
        rest = _SEP_RE.sub("", rest)
        m = _FILLER_RE.match(rest)
        if m and m.group(1).lower() in FILLERS:
            rest = rest[m.end() :]
            continue
        return rest


def gate(transcript: str) -> GateResult:
    """Check the transcript's first word and extract the command."""
    m = _FIRST_WORD_RE.search(transcript)
    if m is None:
        return GateResult(False, "", "")
    first_word = m.group(0).lower().replace("\u2019", "'")
    word = first_word.removesuffix("'s")
    accepted = word in VARIANTS or (
        word not in REAL_WORDS and levenshtein(word, WAKE_WORD) <= MAX_EDITS
    )
    if not accepted:
        return GateResult(False, "", first_word)
    rest = transcript[m.end() :]
    command = _strip_fillers(rest).rstrip()
    return GateResult(True, command, first_word)
