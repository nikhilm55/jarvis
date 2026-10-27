"""What a spoken or typed answer to a confirmation means (FR-SAFE-07, FR-SAFE-02)."""

import re
from typing import Literal

__all__ = ["NO_WORDS", "YES_WORDS", "Meaning", "meaning", "says_phrase", "words"]

Meaning = Literal["yes", "no"]

# FR-SAFE-07's words, exactly: anything else is unclear and gets asked again.
YES_WORDS = ("yes", "confirm", "do it", "go ahead", "send it")
NO_WORDS = ("no", "cancel")
_POLITE = ("please", "thanks", "thank you")
# Share of the phrase's words (after "confirm") an answer must contain to repeat the target.
PHRASE_OVERLAP = 0.8


def words(text: str) -> list[str]:
    """Lower-case alphanumeric words, without a leading "Jarvis" or a trailing "please"."""
    found = re.findall(r"[a-z0-9]+", text.lower())
    if found[:1] == ["jarvis"]:
        found = found[1:]
    joined = " ".join(found)
    for polite in _POLITE:
        if joined.endswith(" " + polite):
            joined = joined[: -len(polite) - 1]
            break
    return joined.split()


def meaning(text: str) -> Meaning | None:
    """ "yes" or "no" when the answer is one of FR-SAFE-07's words, otherwise None (unclear)."""
    joined = " ".join(words(text))
    if joined in YES_WORDS:
        return "yes"
    if joined in NO_WORDS:
        return "no"
    return None


def says_phrase(text: str, phrase: str) -> bool:
    """True when `text` starts with "confirm" and repeats the target of `phrase` (FR-SAFE-02).

    Paths are compared word by word ("~/Downloads/a.txt" is downloads, a, txt), so a spoken
    "confirm rm downloads a dot txt" counts; at least 80 % of the phrase's words must be there.
    """
    said, wanted = words(text), words(phrase)
    if not said or said[0] != "confirm" or wanted[:1] != ["confirm"]:
        return False
    required = wanted[1:]
    if not required:
        return True
    present = set(said[1:])
    hits = sum(1 for word in required if word in present)
    return hits / len(required) >= PHRASE_OVERLAP
