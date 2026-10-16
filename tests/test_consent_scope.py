"""Tests for the consent Scope value type (FRS 5.11.1)."""

import dataclasses
import typing

import pytest

from jarvis.consent.scope import (
    Access,
    Scope,
    ScopeError,
    parse_scopes,
    source_of,
)


def test_scope_error_is_value_error() -> None:
    """ScopeError must be a subclass of ValueError."""
    assert issubclass(ScopeError, ValueError)
    with pytest.raises(ValueError):
        raise ScopeError("boom")


def test_access_literal() -> None:
    """Access is a Literal type with exactly 'read' and 'write'."""
    origin = typing.get_args(Access)
    assert origin == ("read", "write")


def test_scope_dataclass_fields() -> None:
    """Scope is a frozen, ordered dataclass with source and access fields."""
    names = [f.name for f in dataclasses.fields(Scope)]
    assert names == ["source", "access"]
    scope = Scope("a", "read")
    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.access = "write"  # type: ignore[misc]
    assert Scope("a", "read") < Scope("a", "write") < Scope("b", "read")


def test_parse_valid() -> None:
    """Scope.parse handles well-formed scopes."""
    s = Scope.parse("messages.teams:read")
    assert s.source == "messages.teams"
    assert s.access == "read"

    s2 = Scope.parse("screen:write")
    assert s2.source == "screen"
    assert s2.access == "write"

    s3 = Scope.parse("files.documents:read")
    assert s3.source == "files.documents"
    assert s3.access == "read"

    s4 = Scope.parse("calendar.outlook:write")
    assert s4.source == "calendar.outlook"
    assert s4.access == "write"


def test_parse_normalisation() -> None:
    """Scope.parse strips whitespace and lowercases."""
    s = Scope.parse(" Messages.Teams:READ ")
    assert s.source == "messages.teams"
    assert s.access == "read"
    assert str(s) == "messages.teams:read"

    s2 = Scope.parse("  SCREEN:Write  ")
    assert s2.source == "screen"
    assert s2.access == "write"


def test_parse_star_rejected() -> None:
    """Scope.parse rejects '*' access and mentions parse_scopes."""
    with pytest.raises(ScopeError, match="parse_scopes"):
        Scope.parse("messages.teams:*")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "no-colon",
        "a:b:c",
        ":read",
        "messages.teams:",
        "a..b:read",
        "a b:read",
        "a.b:record",
        "a.b:READX",
        "a.b:read write",
        "-abc:read",
        "abc-:read",
        "a.:read",
        "a" * 65 + ":read",
        "messages.teams:*:read",
        "caf\u00e9:read",
    ],
)
def test_parse_malformed(bad: str) -> None:
    """Malformed scope strings raise ScopeError."""
    with pytest.raises(ScopeError):
        Scope.parse(bad)


def test_parse_accepts_digits_and_inner_punctuation() -> None:
    """A segment may start with a digit and hold `_` and `-` inside."""
    assert str(Scope.parse("123:read")) == "123:read"
    assert str(Scope.parse("a_b-c.d2:write")) == "a_b-c.d2:write"
    assert str(Scope.parse("a" * 64 + ":read")) == "a" * 64 + ":read"


def test_parse_rejects_non_strings() -> None:
    """Anything that is not a str is a ScopeError, not a TypeError."""
    with pytest.raises(ScopeError):
        Scope.parse(None)  # type: ignore[arg-type]
    with pytest.raises(ScopeError):
        parse_scopes([3])  # type: ignore[list-item]
    with pytest.raises(ScopeError):
        Scope(3, "read")  # type: ignore[arg-type]
    with pytest.raises(ScopeError):
        Scope("a", 3)  # type: ignore[arg-type]


def test_str_round_trip() -> None:
    """str(Scope.parse(x)) == x for normalised x."""
    original = "messages.teams:read"
    s = Scope.parse(original)
    assert str(s) == original

    original2 = "screen:write"
    s2 = Scope.parse(original2)
    assert str(s2) == original2


def test_post_init_validation() -> None:
    """Scope('bad source', 'read') raises ScopeError via __post_init__."""
    with pytest.raises(ScopeError):
        Scope("bad source", "read")

    with pytest.raises(ScopeError):
        Scope("messages.teams", "record")  # type: ignore[arg-type]

    with pytest.raises(ScopeError):
        Scope("a..b", "read")

    with pytest.raises(ScopeError):
        Scope("a b", "read")


def test_parse_scopes_star_expansion() -> None:
    """'*' access in parse_scopes expands to both read and write scopes."""
    result = parse_scopes(["messages.teams:*"])
    assert len(result) == 2
    assert Scope("messages.teams", "read") in result
    assert Scope("messages.teams", "write") in result


def test_parse_scopes_dedup_and_ordering() -> None:
    """parse_scopes deduplicates and sorts results."""
    result = parse_scopes(["b:read", "a:write", "a:read", "b:read", "a:read"])
    assert result == (
        Scope("a", "read"),
        Scope("a", "write"),
        Scope("b", "read"),
    )


def test_parse_scopes_star_needs_a_valid_source() -> None:
    """The source of a `*` item is validated like any other."""
    with pytest.raises(ScopeError):
        parse_scopes(["bad source:*"])


def test_parse_scopes_bad_item() -> None:
    """A bad item in parse_scopes raises ScopeError."""
    with pytest.raises(ScopeError):
        parse_scopes(["good:read", "bad item:read"])

    with pytest.raises(ScopeError):
        parse_scopes(["no-colon"])


def test_parse_scopes_bare_string() -> None:
    """Passing a bare str to parse_scopes raises ScopeError."""
    with pytest.raises(ScopeError):
        parse_scopes("messages.teams:read")


def test_scope_hashable_dict_key() -> None:
    """Scopes are hashable and usable as dict keys."""
    s = Scope("messages.teams", "read")
    d: dict[Scope, str] = {s: "ok"}
    assert d[s] == "ok"
    assert hash(s) is not None


def test_source_of() -> None:
    """source_of returns sorted distinct sources."""
    scopes = [
        Scope("b", "read"),
        Scope("a", "write"),
        Scope("a", "read"),
        Scope("b", "write"),
    ]
    assert source_of(scopes) == ("a", "b")

    assert source_of([]) == ()
    assert source_of([Scope("x", "read")]) == ("x",)
