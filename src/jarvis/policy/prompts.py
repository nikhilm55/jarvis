"""The question a confirmation asks, in words the user hears (FR-SAFE-07, FR-SAFE-05)."""

from collections.abc import Mapping

from jarvis.policy import registry
from jarvis.policy.lists import command_of, path_args
from jarvis.policy.model import Tier

__all__ = ["describe"]

_MAX_COMMAND = 80
_NAME_KEYS = ("name", "app", "title", "window", "query", "text", "url")
NOT_UNDOABLE = "This can't be undone."


def _target(args: Mapping[str, object], key: str | None) -> str:
    for candidate in (key, *_NAME_KEYS):
        value = args.get(candidate) if candidate else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    paths = path_args(args)
    return ", ".join(paths[:3]) + (f" and {len(paths) - 3} more" if len(paths) > 3 else "")


def describe(name: str, args: Mapping[str, object], tier: Tier | None) -> str:
    """ "Close Firefox?", "Run 'git push --force'?"; T2 and up add whether it can be undone."""
    cmd = command_of(args)
    if cmd:
        shown = cmd if len(cmd) <= _MAX_COMMAND else cmd[: _MAX_COMMAND - 1] + "…"
        question = f"Run '{shown}'?"
    else:
        spec = registry.get(name)
        verb = name.rsplit(".", 1)[-1].replace("_", " ")
        target = _target(args, spec.target_key if spec else None)
        words = f"{verb} {target}".strip()
        question = words[:1].upper() + words[1:] + "?"
    spec = registry.get(name)
    if tier in (Tier.T2, Tier.T3) and not (spec is not None and spec.undoable):
        question += f" {NOT_UNDOABLE}"
    return question
