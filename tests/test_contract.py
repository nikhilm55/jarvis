import json
from pathlib import Path
from typing import Any

import pytest

from jarvis.contract import (
    CONTRACT_VERSION,
    FALLBACK_SPOKEN,
    ContractError,
    FinalResponse,
    TurnEnvelope,
    repair_message,
    validate_response,
    wrap_bare_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contract"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def _problems(obj: object) -> list[str]:
    with pytest.raises(ContractError) as caught:
        validate_response(obj)
    return caught.value.problems


def test_should_validate_the_spec_success_example() -> None:
    response = validate_response(_load("response_success.json"))

    assert response.status == "success"
    assert response.spoken == "Sent to Rahul Sharma."
    assert response.actions_taken[0].tool == "teams.send_message"


def test_should_validate_the_spec_failure_example() -> None:
    response = validate_response(_load("response_failed.json"))

    assert response.error is not None
    assert response.error.code == "NOT_FOUND"
    assert len(response.error.remedy) == 3
    assert response.spoken == (
        "I couldn't find Rohit Kapoor in your Teams contacts. The closest is Rohit Kumar. "
        "Should I open that chat instead?"
    )


def test_should_accept_a_json_string() -> None:
    raw = (FIXTURES / "response_success.json").read_text(encoding="utf-8")

    assert isinstance(validate_response(raw), FinalResponse)


def test_should_sanitise_spoken_when_validating() -> None:
    payload = {"status": "success", "spoken": "**Done** — see https://example.com."}

    assert validate_response(payload).spoken == "Done — see."


def test_should_reject_failed_status_when_error_is_missing() -> None:
    assert _problems({"status": "failed", "spoken": "No."}) == [
        "error: status 'failed' requires an error with code, what, why and a remedy"
    ]


def test_should_reject_failed_status_when_remedy_is_empty() -> None:
    payload = _load("response_failed.json")
    payload["error"]["remedy"] = []

    assert _problems(payload) == ["error.remedy: at least one remedy is required"]


def test_should_reject_an_unknown_status() -> None:
    assert _problems({"status": "done", "spoken": "Ok."})[0].startswith("status: ")


def test_should_reject_an_unknown_error_code() -> None:
    payload = _load("response_failed.json")
    payload["error"]["code"] = "OOPS"

    assert _problems(payload)[0].startswith("error.code: ")


def test_should_reject_an_extra_field() -> None:
    payload = _load("response_success.json") | {"mood": "happy"}

    assert _problems(payload) == ["mood: Extra inputs are not permitted"]


def test_should_raise_contract_error_when_json_is_invalid() -> None:
    assert _problems('{"status": ')[0].startswith("(root): Invalid JSON")


def test_should_raise_contract_error_when_input_is_not_an_object() -> None:
    assert _problems(["success"]) == [
        "(root): Input should be a valid dictionary or instance of FinalResponse"
    ]


def test_should_reject_spoken_when_nothing_speakable_is_left() -> None:
    assert _problems({"status": "success", "spoken": "https://example.com"}) == [
        "spoken: nothing speakable left after sanitising"
    ]


def test_should_reject_blank_error_details() -> None:
    payload = _load("response_failed.json")
    payload["error"] |= {"what": "", "why": "  ", "remedy": ["Retry", ""]}

    assert _problems(payload) == [
        "error.what: String should have at least 1 character",
        "error.why: String should have at least 1 character",
        "error.remedy.1: String should have at least 1 character",
    ]


def test_should_reject_flags_that_are_not_booleans() -> None:
    payload = _load("response_success.json") | {"follow_up_expected": "yes"}
    payload["actions_taken"][0]["undoable"] = 1

    assert _problems(payload) == [
        "actions_taken.0.undoable: Input should be a valid boolean",
        "follow_up_expected: Input should be a valid boolean",
    ]


def test_should_list_every_problem_in_the_repair_message() -> None:
    err = ContractError(["status: bad value", "spoken: Field required"])

    message = repair_message(err)

    assert message.startswith("Your last response failed validation:")
    assert "- status: bad value" in message
    assert "- spoken: Field required" in message
    assert "jarvis.respond" in message


def test_should_wrap_bare_text_as_partial_with_sanitised_spoken() -> None:
    response = wrap_bare_text("# Done\nOpened `~/notes.txt`.")

    assert (response.status, response.spoken, response.display) == (
        "partial",
        "Done. Opened.",
        None,
    )


def test_should_fall_back_when_bare_text_has_nothing_speakable() -> None:
    assert wrap_bare_text("https://example.com").spoken == FALLBACK_SPOKEN


def test_should_parse_the_spec_envelope_example_with_the_current_version() -> None:
    envelope = TurnEnvelope.model_validate(_load("envelope.json"))

    assert envelope.contract_version == CONTRACT_VERSION == "1"
    assert envelope.context.active_window is not None
    assert envelope.policy.grants["email.gmail:read"] == "never"


def test_should_serialise_envelope_as_compact_unescaped_utf8() -> None:
    envelope = TurnEnvelope.model_validate(_load("envelope.json") | {"command": "राहुल को लिखो"})

    text = envelope.to_json()

    assert "राहुल को लिखो" in text
    assert "\n" not in text
    assert TurnEnvelope.model_validate_json(text) == envelope
