"""Policy vocabulary: risk tiers, modes and the immutable tool descriptor."""

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

Mode = Literal["safe", "balanced", "yolo"]


class Tier(enum.StrEnum):
    """Tool risk tiers."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


def max_tier(a: Tier, b: Tier) -> Tier:
    """The riskier of two tiers (T0 < T1 < T2 < T3)."""
    return a if a.value >= b.value else b


# Refines a tool's tier and scopes from its arguments. It may raise the tier, never lower it.
Classifier = Callable[[Mapping[str, object]], tuple[Tier, tuple[str, ...]]]


def _check_name(value: object) -> str:
    """Validate and return a non-blank tool name."""
    if not isinstance(value, str):
        raise ValueError("invalid name: must be a str")
    if not value.strip():
        raise ValueError("invalid name: must be non-blank")
    return value


def _check_tier(value: object) -> Tier:
    """Validate and normalise a tier value."""
    if isinstance(value, Tier):
        return value
    if isinstance(value, str):
        try:
            return Tier(value)
        except ValueError as exc:
            raise ValueError(f"invalid tier {value!r}") from exc
    raise ValueError(f"invalid tier {value!r}")


def _check_scopes(value: object) -> tuple[str, ...]:
    """Validate and normalise scopes to a tuple of strings."""
    if isinstance(value, str) or value is None:
        raise ValueError("invalid scopes: must be a list or tuple")
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid scopes: must be a list or tuple")
    for item in value:
        if not isinstance(item, str):
            raise ValueError("invalid scopes: items must be str")
    return tuple(value)


@dataclass(frozen=True)
class ToolSpec:
    """Immutable tool descriptor."""

    name: str
    tier: Tier
    scopes: tuple[str, ...] = ()
    undoable: bool = False
    classify: Classifier | None = None
    target_key: str | None = None  # the argument that names what the call acts on (YOLO phrase)
    # Arguments that must come from the user's words (R83); none given: just `target_key`.
    provenance_keys: tuple[str, ...] = ()
    reason_key: str | None = None  # the argument that says why, for the consent question
    drives_input: bool = False  # moves the mouse or types: the HUD says so (FR-SAFE-06)

    def __post_init__(self) -> None:
        """Validate and normalise fields on construction."""
        object.__setattr__(self, "name", _check_name(self.name))
        object.__setattr__(self, "tier", _check_tier(self.tier))
        object.__setattr__(self, "scopes", _check_scopes(self.scopes))
        if self.classify is not None and not callable(self.classify):
            raise ValueError("invalid classify: must be callable or None")
