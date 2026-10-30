"""Where a tool argument came from: the user's words, or something Jarvis read (R83, FR-SAFE-03).

A T2+ action's target and content count as the user's only when their words are in what the
user said this turn (the command, or a reply to a question): at least 80 % of a value's words
must be there. Anything else came from content the brain read, and needs the user to confirm
it, in every mode.

Two things the user never spells out don't count against a value: the home folder a path
starts in ("in my home folder" becomes /home/<user>/…), and words that speech-to-text split
("jarvis demo" for a folder named JarvisDemo, "t x t" for txt).
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from jarvis.policy.model import ToolSpec

__all__ = ["OVERLAP", "foreign_values", "user_provided"]

OVERLAP = 0.8
_JOIN = 3  # spoken words joined to match one written word: "t x t" → "txt"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _value_words(value: str, home: Path) -> list[str]:
    """The value's words, without the home folder it starts in; the home folder itself is "home"."""
    text = value.strip().replace("\\", "/")  # one separator, so Windows paths compare too
    for prefix in (home.as_posix(), "~", "$HOME"):
        if text == prefix or text.startswith(prefix + "/"):
            return _words(text[len(prefix) :]) or ["home"]
    return _words(text)


def _said(heard: Sequence[str]) -> set[str]:
    said: set[str] = set()
    for text in heard:
        words = _words(text)
        for size in range(1, _JOIN + 1):
            said.update("".join(words[i : i + size]) for i in range(len(words) - size + 1))
    return said


def user_provided(value: str, heard: Sequence[str], home: Path | None = None) -> bool:
    """True when at least 80 % of `value`'s words are in what the user said."""
    wanted = _value_words(value, home or Path.home())
    if not wanted:
        return True  # nothing that could carry an instruction
    said = _said(heard)
    return sum(1 for word in wanted if word in said) / len(wanted) >= OVERLAP


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def foreign_values(spec: ToolSpec, args: Mapping[str, object], heard: Sequence[str]) -> list[str]:
    """The target and content values of a call that the user did not say."""
    keys = spec.provenance_keys or ((spec.target_key,) if spec.target_key else ())
    values = [text for key in keys for text in _strings(args.get(key))]
    return [text for text in values if not user_provided(text, heard)]
