import json
from pathlib import Path
from typing import Any

from jarvis.contract import CONTRACT_VERSION, TurnEnvelope

FIXTURES = Path(__file__).parent / "fixtures" / "contract"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


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
