"""The tools jarvisd's MCP server exposes to the brain, and their policy-gate names."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jarvis import policy
from jarvis.brain.desktop_tools import WINDOW_OPS
from jarvis.consent.request import MAX_SCOPES, REQUEST_ACCESS
from jarvis.contract import FinalResponse
from jarvis.files import FILE_TOOLS  # noqa: F401 - registers the file tools' policy
from jarvis.files.search import KINDS, WHENS
from jarvis.shell import SHELL_TOOLS  # noqa: F401 - registers the shell tool's policy

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
        name="request_access",
        policy_name=REQUEST_ACCESS,
        description=(
            "Ask the user once, up front, for the personal data a task needs (FR-CON-03). "
            "Returns at once when already allowed; an error with CONSENT_DENIED when refused."
        ),
        input_schema=_object_schema(
            {
                "scopes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^[a-z0-9_.-]+:(read|write|\\*)$"},
                    "minItems": 1,
                    "maxItems": MAX_SCOPES,
                    "description": "e.g. messages.teams:read, calendar.google:write",
                },
                "reason": {
                    "type": "string",
                    "maxLength": 120,
                    "description": "What it is for, e.g. 'read your unread messages'.",
                },
            },
            ["scopes", "reason"],
        ),
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
        name="list_apps",
        policy_name="desktop.list_apps",
        description="List the installed desktop applications (name, id, and where installed from).",
        input_schema=_object_schema({}, []),
    ),
    McpTool(
        name="is_running",
        policy_name="desktop.is_running",
        description="Say whether an application has a window open, and how many.",
        input_schema=_object_schema(
            {"name": {"type": "string", "description": "Application name, e.g. Firefox."}},
            ["name"],
        ),
    ),
    McpTool(
        name="list_windows",
        policy_name="desktop.list_windows",
        description=(
            "List the open windows, frontmost first: ref, title, app, monitor and state "
            "(normal, minimized, maximized, focused)."
        ),
        input_schema=_object_schema({}, []),
    ),
    McpTool(
        name="focus_window",
        policy_name="desktop.focus_window",
        description=(
            "Bring a window to the front and focus it; a minimised window is restored first. "
            "The answer confirms it is focused."
        ),
        input_schema=_object_schema(
            {
                "ref": {
                    "type": "string",
                    "description": "A ref from list_windows, or words of its title or app name.",
                }
            },
            ["ref"],
        ),
    ),
    McpTool(
        name="window_op",
        policy_name="desktop.window_op",
        description=(
            "Minimise, maximise, restore, close, snap left or right, move to another monitor, "
            "or tile windows. Each answer confirms the result."
        ),
        input_schema=_object_schema(
            {
                "ref": {
                    "type": "string",
                    "description": "A ref from list_windows, or words of its title or app name.",
                },
                "op": {"type": "string", "enum": list(WINDOW_OPS)},
                "monitor": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 15,
                    "description": "For move_to_monitor: the monitor, 0 is the leftmost.",
                },
                "with_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 7,
                    "description": "For tile: the other windows to tile with ref.",
                },
            },
            ["ref", "op"],
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
    McpTool(
        name="type_text",
        policy_name="desktop.type_text",
        description=(
            "Type text into the focused field (long text is pasted). Type only what the user "
            "asked for; a line break can run a command in a terminal."
        ),
        input_schema=_object_schema(
            {"text": {"type": "string", "minLength": 1, "maxLength": 5000}}, ["text"]
        ),
    ),
    McpTool(
        name="press_keys",
        policy_name="desktop.press_keys",
        description="Press a key or combination, e.g. 'ctrl+s', 'alt+tab', 'enter', 'f5'.",
        input_schema=_object_schema(
            {"combo": {"type": "string", "minLength": 1, "maxLength": 40}}, ["combo"]
        ),
    ),
    McpTool(
        name="click",
        policy_name="desktop.click",
        description="Click at screen coordinates (prefer focus_window and keys when you can).",
        input_schema=_object_schema(
            {
                "x": {"type": "integer", "minimum": 0},
                "y": {"type": "integer", "minimum": 0},
                "button": {"type": "string", "enum": ["left", "middle", "right"]},
                "count": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            ["x", "y"],
        ),
    ),
    McpTool(
        name="scroll",
        policy_name="desktop.scroll",
        description="Scroll by notches: dy > 0 down, dy < 0 up; dx > 0 right, dx < 0 left.",
        input_schema=_object_schema(
            {
                "dx": {"type": "integer", "minimum": -50, "maximum": 50},
                "dy": {"type": "integer", "minimum": -50, "maximum": 50},
            },
            [],
        ),
    ),
    McpTool(
        name="run_shell",
        policy_name="shell.run",
        description=(
            "Run one shell command on this PC and get stdout, stderr and the exit code. "
            "Prefer the dedicated tools for files, windows, and input."
        ),
        input_schema=_object_schema(
            {
                "cmd": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                    "description": "One command line.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Folder to run in (default: the home folder).",
                },
                "timeout_s": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "description": "Kill the command after this many seconds (default: 60).",
                },
            },
            ["cmd"],
        ),
    ),
    McpTool(
        name="search_files",
        policy_name="files.search",
        description=(
            "Find files by name (words in any order) under a folder, newest first; "
            "optional when (today, yesterday, this week, last week, this month) and kind."
        ),
        input_schema=_object_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "folder": {"type": "string", "description": "Default: the home folder."},
                "when": {"type": "string", "enum": list(WHENS)},
                "kind": {"type": "string", "enum": [*KINDS, "folder"]},
            },
            ["query"],
        ),
    ),
    McpTool(
        name="open_file",
        policy_name="files.open",
        description="Open a file or folder with its default app.",
        input_schema=_object_schema({"path": {"type": "string"}}, ["path"]),
    ),
    McpTool(
        name="reveal_file",
        policy_name="files.reveal",
        description="Show a file in the file manager.",
        input_schema=_object_schema({"path": {"type": "string"}}, ["path"]),
    ),
    McpTool(
        name="trash_files",
        policy_name="files.trash",
        description=(
            "Delete = move to the trash (undoable). contents=true trashes everything inside "
            "each folder. Say the result's summary."
        ),
        input_schema=_object_schema(
            {
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "contents": {"type": "boolean"},
            },
            ["paths"],
        ),
    ),
    McpTool(
        name="delete_files_permanently",
        policy_name="files.delete_permanently",
        description="Delete for good, only when the user said 'permanently'. Never undoable.",
        input_schema=_object_schema(
            {"paths": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, ["paths"]
        ),
    ),
    McpTool(
        name="move_files",
        policy_name="files.move",
        description="Move files or folders into a folder (undoable). Nothing is overwritten.",
        input_schema=_object_schema(
            {
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "dest": {"type": "string"},
            },
            ["paths", "dest"],
        ),
    ),
    McpTool(
        name="copy_files",
        policy_name="files.copy",
        description="Copy files or folders into a folder. Nothing is overwritten.",
        input_schema=_object_schema(
            {
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "dest": {"type": "string"},
            },
            ["paths", "dest"],
        ),
    ),
    McpTool(
        name="rename_file",
        policy_name="files.rename",
        description="Rename a file or folder in place (undoable); name is a plain file name.",
        input_schema=_object_schema(
            {"path": {"type": "string"}, "name": {"type": "string"}}, ["path", "name"]
        ),
    ),
    McpTool(
        name="zip_files",
        policy_name="files.zip",
        description="Make a new .zip of files and folders at dest.",
        input_schema=_object_schema(
            {
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "dest": {"type": "string"},
            },
            ["paths", "dest"],
        ),
    ),
)

TOOLS_BY_NAME: Mapping[str, McpTool] = {tool.name: tool for tool in TOOLS}
