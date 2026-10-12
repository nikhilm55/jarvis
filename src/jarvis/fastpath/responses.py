"""Spoken lines and FinalResponse builders for the fast path (FR-TALK-05, FR-IO-03)."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast, get_args

from jarvis import policy
from jarvis.contract import ActionTaken, ErrorCode, ErrorInfo, FinalResponse
from jarvis.desktop.client import DesktopError

__all__ = [
    "blocked",
    "desktop_failure",
    "ok",
    "percent_of",
    "spoken_date",
    "spoken_time",
    "text_of",
]

_DAYS = tuple("Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split())  # noqa: SIM905
_MONTHS = tuple(
    "January February March April May June July August September October November December".split()  # noqa: SIM905
)
_REMEDY = {
    "TIMEOUT": "Try again in a moment.",
    "UNSUPPORTED_ON_PLATFORM": (
        "This isn't supported on your desktop yet, so please do it yourself for now."
    ),
    "ELEVATED_WINDOW": "Close that window yourself, or run Jarvis's admin helper.",
    "NOT_FOUND": "Check the name and ask again.",
    "AMBIGUOUS": "Say which one you mean.",
}


def blocked(decision: policy.Decision, mode: policy.Mode) -> FinalResponse:
    """Build a failed response for a policy-blocked action."""
    reason = decision.reason if decision.reason.strip() else "no reason given"
    if mode == "safe" and "confirmation" in decision.reason:
        spoken = "I can't do that in safe mode yet. Switch to balanced mode and ask again."
        remedy = ["Switch to balanced mode in Settings, then ask again."]
    else:
        spoken = "I didn't do that because the safety check refused it."
        remedy = ["Check the activity log for the reason."]
    return FinalResponse(
        status="failed",
        spoken=spoken,
        error=ErrorInfo(
            code="BLOCKED_BY_POLICY",
            what="The safety check refused that action",
            why=reason,
            remedy=remedy,
        ),
        actions_taken=[],
    )


def ok(
    spoken: str,
    tool: str | None,
    summary: str = "",
    *,
    undoable: bool = False,
) -> FinalResponse:
    """Build a success response, optionally recording an action."""
    actions = (
        [ActionTaken(tool=tool, summary=summary, undoable=undoable)] if tool is not None else []
    )
    return FinalResponse(status="success", spoken=spoken, actions_taken=actions)


def text_of(result: Mapping[str, object], key: str, default: str) -> str:
    """Return the non-blank string at key, else default."""
    value = result.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def percent_of(result: Mapping[str, object], default: int) -> int:
    """Return the integer percent at key, else default."""
    value = result.get("percent")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def desktop_failure(action: str, exc: DesktopError) -> FinalResponse:
    """Build a failed response for a desktop worker error."""
    code = cast(ErrorCode, exc.code if exc.code in get_args(ErrorCode) else "INTERNAL")
    remedy = _REMEDY.get(exc.code, "Check the activity log for details.")
    return FinalResponse(
        status="failed",
        spoken=f"I couldn't {action}. {remedy}",
        error=ErrorInfo(
            code=code,
            what=f"Could not {action}",
            why=exc.message or "The desktop worker reported an error",
            remedy=[remedy],
        ),
        actions_taken=[],
    )


def spoken_time(now: datetime) -> str:
    """Return the 12-hour spoken time string for the given datetime."""
    hour12 = now.hour % 12 or 12
    suffix = "AM" if now.hour < 12 else "PM"
    return f"It's {hour12}:{now.minute:02d} {suffix}."


def spoken_date(now: datetime) -> str:
    """Return the spoken date string for the given datetime."""
    return f"It's {_DAYS[now.weekday()]}, {now.day} {_MONTHS[now.month - 1]}."
