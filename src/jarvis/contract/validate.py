"""Validate `jarvis.respond` payloads and build the FR-IO-01 repair prompt and fallbacks."""

from typing import get_args

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from jarvis.contract.models import CONTRACT_VERSION, ErrorCode, FinalResponse, Status
from jarvis.contract.sanitise import sanitise_spoken

FALLBACK_SPOKEN = "Something went wrong on my side — the details are in the activity log."


class ContractError(Exception):
    """A `jarvis.respond` payload broke the contract; `problems` holds one line per violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_response(obj: object) -> FinalResponse:
    """Parse a dict or JSON string into a FinalResponse with `spoken` sanitised (FR-IO-01/02)."""
    try:
        if isinstance(obj, str):
            response = FinalResponse.model_validate_json(obj)
        else:
            response = FinalResponse.model_validate(obj)
    except ValidationError as exc:
        raise ContractError([_describe(error) for error in exc.errors()]) from exc
    spoken = sanitise_spoken(response.spoken)
    if not spoken:  # Jarvis is never silent (FR-TALK-01): make the brain repair it
        raise ContractError(["spoken: nothing speakable left after sanitising"])
    return response.model_copy(update={"spoken": spoken})


def _describe(error: ErrorDetails) -> str:
    path = ".".join(str(part) for part in error["loc"]) or "(root)"
    return f"{path}: {error['msg']}"


def repair_message(err: ContractError) -> str:
    """The one-shot repair prompt sent back to the brain after an invalid response (FR-IO-01)."""
    problems = "\n".join(f"- {problem}" for problem in err.problems)
    return (
        f"Your last response failed validation:\n{problems}\n"
        "End this turn with exactly one jarvis.respond call whose payload matches the "
        f"contract (version {CONTRACT_VERSION}): status, spoken, display, error, actions_taken, "
        f"follow_up_expected. status is one of: {', '.join(get_args(Status))}. "
        "status 'failed' needs an error with code, what, why and at least one remedy; "
        f"error.code is one of: {', '.join(get_args(ErrorCode))}."
    )


def wrap_bare_text(text: str) -> FinalResponse:
    """Wrap bare brain output as a 'partial' response (FR-IO-06); the caller logs the violation."""
    return FinalResponse(status="partial", spoken=sanitise_spoken(text) or FALLBACK_SPOKEN)
