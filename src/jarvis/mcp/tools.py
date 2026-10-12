"""The tools jarvisd's MCP server exposes to the brain, and their policy-gate names."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jarvis import policy
from jarvis.contract import FinalResponse

SERVER_NAME = "jarvis"


@dataclass(frozen=True)
class McpTool:
    """A tool exposed by the MCP server, mapped to its policy-gate name."""

    name: str
    policy_name: str
    description: str
    input_schema: dict[str, Any]


for _name in ("jarvis.say", "jarvis.ask", "jarvis.respond"):
    policy.register(policy.ToolSpec(_name, policy.Tier.T0))


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Build a JSON object schema, omitting the required key when it is empty."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


_FINAL_RESPONSE_SCHEMA: dict[str, Any] = FinalResponse.model_json_schema()

TOOLS: tuple[McpTool, ...] = (
    McpTool(
        name="say",
        policy_name="jarvis.say",
        description=(
            "Speak one short progress sentence aloud while you work. "
            "Use it at most once per step; never use it for the final answer."
        ),
        input_schema=_object_schema(
            {"text": {"type": "string", "description": "One short sentence to speak."}},
            ["text"],
        ),
    ),
    McpTool(
        name="ask",
        policy_name="jarvis.ask",
        description=(
            "Ask the user a question out loud and return their spoken answer. "
            "Use it only when you cannot continue without their choice."
        ),
        input_schema=_object_schema(
            {
                "question": {
                    "type": "string",
                    "description": "The question to speak.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional answers to offer.",
                },
            },
            ["question"],
        ),
    ),
    McpTool(
        name="respond",
        policy_name="jarvis.respond",
        description=(
            "Finish the turn with the final structured response. "
            "You MUST call this exactly once to end every turn."
        ),
        input_schema=_FINAL_RESPONSE_SCHEMA,
    ),
    McpTool(
        name="open_app",
        policy_name="desktop.open_app",
        description="Open or focus a desktop application by name.",
        input_schema=_object_schema(
            {
                "name": {
                    "type": "string",
                    "description": "Application name, e.g. Firefox.",
                }
            },
            ["name"],
        ),
    ),
    McpTool(
        name="close_app",
        policy_name="desktop.close_app",
        description="Close the windows of a desktop application by name.",
        input_schema=_object_schema(
            {
                "name": {
                    "type": "string",
                    "description": "Application name, e.g. Firefox.",
                }
            },
            ["name"],
        ),
    ),
    McpTool(
        name="volume_get",
        policy_name="desktop.volume_get",
        description="Read the current system volume percentage and whether it is muted.",
        input_schema=_object_schema({}, []),
    ),
    McpTool(
        name="volume_set",
        policy_name="desktop.volume_set",
        description="Set the system volume to an exact percentage.",
        input_schema=_object_schema(
            {
                "percent": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Volume from 0 to 100.",
                }
            },
            ["percent"],
        ),
    ),
    McpTool(
        name="volume_step",
        policy_name="desktop.volume_step",
        description=(
            "Raise or lower the system volume by a number of percentage points; negative lowers."
        ),
        input_schema=_object_schema(
            {
                "delta": {
                    "type": "integer",
                    "description": "Signed percentage points to change by.",
                }
            },
            ["delta"],
        ),
    ),
    McpTool(
        name="mute",
        policy_name="desktop.mute",
        description="Mute or unmute the system audio.",
        input_schema=_object_schema(
            {
                "on": {
                    "type": "boolean",
                    "description": "True to mute, false to unmute.",
                }
            },
            ["on"],
        ),
    ),
)

TOOLS_BY_NAME: Mapping[str, McpTool] = {tool.name: tool for tool in TOOLS}
