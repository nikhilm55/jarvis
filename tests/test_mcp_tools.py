"""Tests for jarvis.mcp.tools."""

import re

import pytest

from jarvis import policy
from jarvis.contract import FinalResponse
from jarvis.mcp.tools import SERVER_NAME, TOOLS, TOOLS_BY_NAME, McpTool

EXPECTED_NAMES = (
    "say",
    "ask",
    "respond",
    "open_app",
    "close_app",
    "volume_get",
    "volume_set",
    "volume_step",
    "mute",
)

POLICY_MAP = {
    "say": "jarvis.say",
    "ask": "jarvis.ask",
    "respond": "jarvis.respond",
    "open_app": "desktop.open_app",
    "close_app": "desktop.close_app",
    "volume_get": "desktop.volume_get",
    "volume_set": "desktop.volume_set",
    "volume_step": "desktop.volume_step",
    "mute": "desktop.mute",
}


def test_should_expose_nine_tools_in_order_when_module_loaded() -> None:
    assert [t.name for t in TOOLS] == list(EXPECTED_NAMES)


def test_should_use_jarvis_as_server_name_when_module_loaded() -> None:
    assert SERVER_NAME == "jarvis"


def test_should_map_names_to_same_tool_objects_when_indexed() -> None:
    assert set(TOOLS_BY_NAME) == set(EXPECTED_NAMES)
    for tool in TOOLS:
        assert TOOLS_BY_NAME[tool.name] is tool


@pytest.mark.parametrize("name,policy_name", list(POLICY_MAP.items()))
def test_should_map_tool_to_policy_name_when_lookup(name: str, policy_name: str) -> None:
    assert TOOLS_BY_NAME[name].policy_name == policy_name


@pytest.mark.parametrize("name", ["jarvis.say", "jarvis.ask", "jarvis.respond"])
def test_should_register_jarvis_tools_as_t0_no_scope_when_imported(name: str) -> None:
    spec = policy.get(name)
    assert spec is not None
    assert spec.tier is policy.Tier.T0
    assert spec.scopes == ()


@pytest.mark.parametrize("tool", TOOLS)
def test_should_have_registered_policy_when_tool_exists(tool: McpTool) -> None:
    assert policy.get(tool.policy_name) is not None


@pytest.mark.parametrize("tool", TOOLS)
def test_should_have_valid_name_and_description_when_tool_exists(tool: McpTool) -> None:
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tool.name)
    assert tool.description.strip()
    assert len(tool.description) <= 300


@pytest.mark.parametrize("tool", TOOLS)
def test_should_have_object_type_schema_when_tool_exists(tool: McpTool) -> None:
    assert tool.input_schema["type"] == "object"


def test_should_match_final_response_schema_when_respond_used() -> None:
    assert TOOLS_BY_NAME["respond"].input_schema == FinalResponse.model_json_schema()


@pytest.mark.parametrize("tool", TOOLS)
def test_should_forbid_additional_properties_when_not_respond(tool: McpTool) -> None:
    if tool.name != "respond":
        assert tool.input_schema.get("additionalProperties") is False


def test_should_require_text_when_say_schema_used() -> None:
    assert TOOLS_BY_NAME["say"].input_schema["required"] == ["text"]


def test_should_require_question_and_allow_options_when_ask_schema_used() -> None:
    schema = TOOLS_BY_NAME["ask"].input_schema
    assert schema["required"] == ["question"]
    options = schema["properties"]["options"]
    assert options["type"] == "array"
    assert options["items"] == {"type": "string"}


def test_should_constrain_percent_when_volume_set_schema_used() -> None:
    percent = TOOLS_BY_NAME["volume_set"].input_schema["properties"]["percent"]
    assert percent["type"] == "integer"
    assert percent["minimum"] == 0
    assert percent["maximum"] == 100


def test_should_require_integer_delta_when_volume_step_schema_used() -> None:
    delta = TOOLS_BY_NAME["volume_step"].input_schema["properties"]["delta"]
    assert delta["type"] == "integer"


def test_should_require_boolean_when_mute_schema_used() -> None:
    on = TOOLS_BY_NAME["mute"].input_schema["properties"]["on"]
    assert on["type"] == "boolean"


def test_should_have_empty_properties_when_volume_get_schema_used() -> None:
    schema = TOOLS_BY_NAME["volume_get"].input_schema
    assert schema["properties"] == {}
    assert schema.get("required", []) == []


@pytest.mark.parametrize("name", ["open_app", "close_app"])
def test_should_require_string_name_when_app_tools_used(name: str) -> None:
    prop = TOOLS_BY_NAME[name].input_schema["properties"]["name"]
    assert prop["type"] == "string"
