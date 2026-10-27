"""Consent Scope value type (FRS 5.11.1)."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, cast

Access = Literal["read", "write"]

_SOURCE_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9_-]*[a-z0-9])?)*$")


class ScopeError(ValueError):
    """Raised for every malformed scope."""


def _validate_source(source: str) -> None:
    """Validate that a source string matches the source rule."""
    if not isinstance(source, str):
        raise ScopeError(f"source must be a str, got {type(source).__name__}")
    if len(source) > 64:
        raise ScopeError(f"source too long: {len(source)} > 64")
    if not _SOURCE_RE.fullmatch(source):
        raise ScopeError(f"invalid source: {source!r}")


def _validate_access(access: str) -> None:
    """Validate that an access string is exactly 'read' or 'write'."""
    if not isinstance(access, str):
        raise ScopeError(f"access must be a str, got {type(access).__name__}")
    if access not in ("read", "write"):
        raise ScopeError(f"invalid access: {access!r}")


def _split(text: object) -> tuple[str, str]:
    """Normalise `text` (strip, lowercase) and split it into source and access."""
    if not isinstance(text, str):
        raise ScopeError(f"expected str, got {type(text).__name__}")
    stripped = text.strip().lower()
    if not stripped:
        raise ScopeError("empty scope")
    parts = stripped.split(":")
    if len(parts) != 2:
        raise ScopeError(f"expected exactly one ':', got {len(parts) - 1}")
    return parts[0], parts[1]


@dataclass(frozen=True, order=True)
class Scope:
    """A consent scope: a data source plus an access, e.g. messages.teams:read."""

    source: str
    access: Access

    def __post_init__(self) -> None:
        """Validate fields on construction."""
        _validate_source(self.source)
        _validate_access(self.access)

    def __str__(self) -> str:
        """Return the canonical form source:access."""
        return f"{self.source}:{self.access}"

    @classmethod
    def parse(cls, text: str) -> "Scope":
        """Parse a scope string like 'messages.teams:read'."""
        source, access = _split(text)
        if access == "*":
            raise ScopeError("wildcard access '*' is not allowed in Scope.parse; use parse_scopes")
        return cls(source, cast(Access, access))


def parse_scopes(items: Iterable[str]) -> tuple[Scope, ...]:
    """Parse an iterable of scope strings, expanding '*' to read and write."""
    if isinstance(items, str):
        raise ScopeError("expected an iterable of str, got a bare str")
    scopes: set[Scope] = set()
    for item in items:
        source, access = _split(item)
        _validate_source(source)
        if access == "*":
            scopes.add(Scope(source, "read"))
            scopes.add(Scope(source, "write"))
        else:
            _validate_access(access)
            scopes.add(Scope(source, cast(Access, access)))
    return tuple(sorted(scopes))


def source_of(scopes: Iterable[Scope]) -> tuple[str, ...]:
    """Return the sorted distinct sources from an iterable of scopes."""
    return tuple(sorted({s.source for s in scopes}))
