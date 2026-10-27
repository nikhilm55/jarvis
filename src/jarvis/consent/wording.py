"""Scopes in the words the user hears (FR-CON-04): what, where, and never read+write bundled.

"messages.teams:read" -> "read your Teams messages"; with ":write" too ->
"read and send your Teams messages". The card's badge is "messages · Teams".
"""

from collections.abc import Iterable

__all__ = ["badge", "describe", "source_name"]

# category -> (read verb, write verb, object; {app} is the source's second part)
_PHRASES: dict[str, tuple[str, str, str]] = {
    "messages": ("read", "send", "your {app} messages"),
    "email": ("read", "send", "your {app} email"),
    "calendar": ("see", "change", "your {app} calendar"),
    "contacts": ("look up", "change", "your {app} contacts"),
    "files": ("read", "change", "files in your {app} folder"),
    "screen": ("see", "control", "your screen"),
    "clipboard": ("read", "change", "your clipboard"),
    "browser": ("read", "act in", "your logged-in browser pages and history"),
    "notes": ("read", "change", "your {app} notes"),
    "notifications": ("read", "dismiss", "your notifications"),
    "meetings": ("read", "record", "your meeting recordings"),
    "home": ("check", "control", "your {app} smart home devices"),
    "memory": ("read", "remember", "things about you"),
}
_APP_NAMES = {
    "m365": "Microsoft 365",
    "gmail": "Gmail",
    "whatsapp": "WhatsApp",
    "outlook": "Outlook",
    "obsidian": "Obsidian",
}


def source_name(source: str) -> str:
    """ "messages.teams" -> "Teams"; a source with no app part names its category."""
    category, _, app = source.partition(".")
    name = app or category
    return _APP_NAMES.get(name, name.replace("_", " ").replace("-", " ").title())


def _phrase(source: str, accesses: set[str]) -> str:
    category, _, app = source.partition(".")
    read, write, thing = _PHRASES.get(category, ("read", "change", "your {app} {category}"))
    obj = " ".join(thing.format(app=source_name(source) if app else "", category=category).split())
    if accesses == {"read", "write"}:
        return f"{read} and {write} {obj}"
    return f"{write if 'write' in accesses else read} {obj}"


def _grouped(scopes: Iterable[str]) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {}
    for scope in scopes:
        source, _, access = scope.partition(":")
        sources.setdefault(source, set()).add(access)
    return sources


def describe(scopes: Iterable[str]) -> str:
    """ "read your Teams messages and see your Google calendar" (sorted by source)."""
    phrases = [_phrase(source, acc) for source, acc in sorted(_grouped(scopes).items())]
    if len(phrases) <= 1:
        return "".join(phrases)
    return ", ".join(phrases[:-1]) + " and " + phrases[-1]


def badge(scopes: Iterable[str]) -> str:
    """The card's corner badge: "messages · Teams", or "3 sources"."""
    sources = sorted(_grouped(scopes))
    if len(sources) != 1:
        return f"{len(sources)} sources"
    category, _, app = sources[0].partition(".")
    return f"{category} · {source_name(sources[0])}" if app else category
