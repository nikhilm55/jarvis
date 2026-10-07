"""Pydantic models for the brain↔Jarvis I/O contract (FRS §5.6.1, §5.6.3, Appendix B)."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError

CONTRACT_VERSION = "1"

Status = Literal["success", "partial", "failed", "needs_input", "cancelled"]

ErrorCode = Literal[
    "NOT_FOUND",
    "AMBIGUOUS",
    "APP_NOT_INSTALLED",
    "AUTH_REQUIRED",
    "PERMISSION_DENIED",
    "INTEGRATION_NOT_CONNECTED",
    "MCP_UNAVAILABLE",
    "BRAIN_UNAVAILABLE",
    "STT_UNAVAILABLE",
    "UNSUPPORTED_ON_PLATFORM",
    "ELEVATED_WINDOW",
    "CONSENT_DENIED",
    "CONSENT_TIMEOUT",
    "BLOCKED_BY_POLICY",
    "CANCELLED",
    "TIMEOUT",
    "NETWORK",
    "PC_LOCKED",
    "INTERNAL",
]


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Final response (brain → Jarvis) ────────────────────────────────────────


class ErrorInfo(_Strict):
    code: ErrorCode
    what: NonBlankText
    why: NonBlankText
    remedy: list[NonBlankText]

    @field_validator("remedy")
    @classmethod
    def _needs_a_remedy(cls, remedy: list[str]) -> list[str]:
        if not remedy:
            raise PydanticCustomError("remedy_required", "at least one remedy is required")
        return remedy


class ActionTaken(_Strict):
    tool: str
    summary: str
    undoable: StrictBool


class Display(_Strict):
    title: str
    body_md: str
    card: str | None = None


class FinalResponse(_Strict):
    status: Status
    spoken: str
    display: Display | None = None
    error: ErrorInfo | None = Field(default=None, validate_default=True)
    actions_taken: list[ActionTaken] = Field(default_factory=list)
    follow_up_expected: StrictBool = False

    @field_validator("error")
    @classmethod
    def _failure_needs_error(
        cls, error: ErrorInfo | None, info: ValidationInfo
    ) -> ErrorInfo | None:
        if error is None and info.data.get("status") == "failed":  # FR-IO-03
            raise PydanticCustomError(
                "error_required",
                "status 'failed' requires an error with code, what, why and a remedy",
            )
        return error


# ── Turn envelope (Jarvis → brain) ─────────────────────────────────────────


class SttInfo(_Strict):
    engine: str
    confidence: float
    language: str


class UserInfo(_Strict):
    name: str
    address_as: str


class ActiveWindow(_Strict):
    app: str
    title: str


class TurnContext(_Strict):
    os: str
    display_server: str | None
    locale: str
    local_time: str
    user: UserInfo
    active_window: ActiveWindow | None = None
    selection_text: str | None = None
    defaults: dict[str, str] = Field(default_factory=dict)
    recent_entities: list[dict[str, Any]] = Field(default_factory=list)  # free-form in §5.6.1
    pending_question: str | None = None


class TurnPolicy(_Strict):
    mode: Literal["safe", "balanced", "yolo"]
    max_steps: int = 25
    grants: dict[str, str] = Field(default_factory=dict)


class TurnEnvelope(_Strict):
    turn_id: str
    command: str
    raw_transcript: str
    stt: SttInfo
    input_mode: Literal["voice", "typed"]
    context: TurnContext
    policy: TurnPolicy
    contract_version: str = CONTRACT_VERSION

    def to_json(self) -> str:
        """Compact JSON; non-ASCII text (e.g. Hindi) stays readable UTF-8, not \\u-escaped."""
        return self.model_dump_json()
