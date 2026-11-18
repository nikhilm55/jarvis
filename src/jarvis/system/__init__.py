"""The system-control tools (FR-PC-06/07/13) and their policy: one tier each.

These are the owner's own PC controls — no personal data travels with them, so they
need no consent scopes; the tier and the mode table decide. Lock is T1 (FR-PC-07
makes lock the mild one; sleep, sign out, restart and shutdown are T3). open_url is
T1 (FRS §5.10 does not rank visiting a page as outward-facing) with R83 provenance
on the URL: an address that did not come from the owner's words is confirmed even
in YOLO. system_info is T0 (read-only).

`device` names what the call switches (the R83 target), `action` the media key or
the power word.
"""

from jarvis.policy import Tier, ToolSpec, register

SYSTEM_TOOLS = (
    ToolSpec("system.output_device", Tier.T1, target_key="device"),
    ToolSpec("system.dnd", Tier.T1),
    ToolSpec("system.dark_mode", Tier.T1),
    ToolSpec("system.night_light", Tier.T1),
    ToolSpec("system.brightness", Tier.T1),
    ToolSpec("system.media", Tier.T1, target_key="action"),
    ToolSpec("system.wifi", Tier.T1),
    ToolSpec("system.bluetooth", Tier.T1),
    ToolSpec("system.lock", Tier.T1),
    ToolSpec("system.power", Tier.T3, target_key="action"),
    ToolSpec("system.open_url", Tier.T1, provenance_keys=("url",)),
    ToolSpec("system.info", Tier.T0),
)

for _spec in SYSTEM_TOOLS:
    register(_spec)

__all__ = ["SYSTEM_TOOLS"]
