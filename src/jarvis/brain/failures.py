"""Failed-turn responses and the BrainUnavailable error (FRS FR-BRN-10, Appendix B)."""

from jarvis.contract import (
    FALLBACK_SPOKEN,
    ErrorCode,
    ErrorInfo,
    FinalResponse,
    sanitise_spoken,
)

__all__ = ["BrainUnavailable", "ToolError", "failed_response"]


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
