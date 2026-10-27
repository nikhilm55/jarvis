"""Where a tool argument came from: the user's words, or something Jarvis read (R83, FR-SAFE-03).

A T2+ action's target and content count as the user's only when their words are in what the
user said this turn (the command, or a reply to a question): at least 80 % of a value's words
must be there. Anything else came from content the brain read, and needs the user to confirm
it, in every mode.
"""

import re
from collections.abc import Mapping, Sequence

from jarvis.policy.model import ToolSpec

__all__ = ["OVERLAP", "foreign_values", "user_provided"]

OVERLAP = 0.8


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def user_provided(value: str, heard: Sequence[str]) -> bool:
    """True when at least 80 % of `value`'s words are in what the user said."""
    wanted = _words(value)
    if not wanted:
        return True  # nothing that could carry an instruction
    said = {word for text in heard for word in _words(text)}
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
