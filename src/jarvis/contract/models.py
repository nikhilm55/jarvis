"""Pydantic models for the brain↔Jarvis I/O contract: the turn envelope (FRS §5.6.1)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
