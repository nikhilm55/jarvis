"""Failed-turn responses and the BrainUnavailable error (FRS FR-BRN-10, Appendix B)."""

from jarvis.brain.stderr_log import stderr_log_path
from jarvis.contract import (
    FALLBACK_SPOKEN,
    ErrorCode,
    ErrorInfo,
    FinalResponse,
    sanitise_spoken,
)

__all__ = [
    "BrainUnavailable",
    "ToolError",
    "contract_fallback",
    "failed_response",
    "internal_response",
    "mcp_unavailable_response",
    "process_exit_response",
    "result_error_response",
    "step_limit_response",
    "timeout_response",
]


class ToolError(Exception):
    """A tool call the model should see as an error; the message is shown to the model."""


def failed_response(
    code: ErrorCode,
    what: str,
    why: str,
    remedy: list[str],
    spoken: str,
) -> FinalResponse:
    """Build a failed FinalResponse with a sanitised spoken line and ErrorInfo."""
    clean = sanitise_spoken(spoken)
    return FinalResponse(
        status="failed",
        spoken=clean if clean else FALLBACK_SPOKEN,
        error=ErrorInfo(code=code, what=what, why=why, remedy=remedy),
    )


class BrainUnavailable(Exception):
    """Raised when the brain cannot run; carries code, what, why and remedy."""

    def __init__(
        self,
        why: str,
        remedy: list[str],
        *,
        code: ErrorCode = "BRAIN_UNAVAILABLE",
    ) -> None:
        """Store the failure details and initialise the exception message."""
        self.code = code
        self.what = "Reach my AI brain"
        self.why = why
        self.remedy = remedy
        super().__init__(why)

    def to_response(self) -> FinalResponse:
        """Render this failure as a failed FinalResponse."""
        spoken = f"My AI brain isn't available: {self.why}. {self.remedy[0]}"
        return failed_response(self.code, self.what, self.why, self.remedy, spoken)


def contract_fallback() -> FinalResponse:
    """The response when the brain broke the respond contract twice (FR-IO-01)."""
    return failed_response(
        "INTERNAL",
        "Answer your request",
        "The AI brain did not follow the response format, even after a correction.",
        ["Ask again.", "The details are in the activity log."],
        FALLBACK_SPOKEN,
    )


def step_limit_response(max_steps: int) -> FinalResponse:
    """The partial response when the brain ignored the step limit (FR-BRN-07)."""
    return FinalResponse(
        status="partial",
        spoken=f"I stopped after {max_steps} steps, so what I did may be incomplete.",
    )


_LOGIN_REMEDY = "Run claude in a terminal and log in, then ask again."
_LIMIT_WORDS = ("usage limit", "rate limit", "quota", "credit", "billing")


def result_error_response(result: str, assistant_error: str | None) -> FinalResponse:
    """Map a Claude Code error result (FR-BRN-10) to a failed response with a remedy."""
    text = result.lower()
    if assistant_error == "authentication_failed" or "not logged in" in text:
        return BrainUnavailable("Claude Code isn't logged in", [_LOGIN_REMEDY]).to_response()
    if assistant_error in ("billing_error", "rate_limit") or any(w in text for w in _LIMIT_WORDS):
        return BrainUnavailable(
            "the Claude usage limit has been reached",
            ["Wait for the limit to reset, or check your Claude plan."],
        ).to_response()
    if assistant_error == "server_error" or "overloaded" in text:
        return BrainUnavailable(
            "Claude's service had a problem", ["Try again in a moment."]
        ).to_response()
    return BrainUnavailable(
        "Claude Code reported an error", ["Try again.", "The details are in the activity log."]
    ).to_response()


def internal_response() -> FinalResponse:
    """The failed response when the brain session itself hit an unexpected error."""
    return failed_response(
        "INTERNAL",
        "Answer your request",
        "The AI brain session hit an unexpected error.",
        ["Ask again.", "The details are in the activity log."],
        FALLBACK_SPOKEN,
    )


def timeout_response(timeout_s: int) -> FinalResponse:
    """The failed response when a turn ran past its wall-time limit (FR-BRN-07)."""
    return failed_response(
        "TIMEOUT",
        "Finish your request",
        f"The AI brain did not finish within {timeout_s} seconds.",
        ["Ask again.", "Try a simpler request."],
        "That took too long, so I stopped. Please try again.",
    )


def process_exit_response() -> FinalResponse:
    """The failed response when the Claude Code process died mid-turn."""
    return BrainUnavailable(
        "the Claude Code process stopped unexpectedly",
        ["Ask again and I'll restart it.", f"What it printed is in {stderr_log_path()}."],
    ).to_response()


def mcp_unavailable_response() -> FinalResponse:
    """The failed response when Claude Code could not reach Jarvis's tool server."""
    return failed_response(
        "MCP_UNAVAILABLE",
        "Reach my tools",
        "Claude Code could not connect to Jarvis's tool server.",
        ["Ask again; the connection is restarted for each new try."],
        "My tools aren't connected right now. Please try again in a moment.",
    )
