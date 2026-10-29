"""The file tools (FR-PC-08) and their policy: tiers, scopes from paths, undo (R90).

Every argument that names a file uses a path key ("path", "paths", "dest", "folder"), so the
gate asks for the consent folder scopes they fall in; the tools that act on a whole tree also
need the scopes of the folders inside (walks_tree). Delete means the trash (T2, undoable);
"permanently" is T3, which the YOLO guardrail confirms by repeating the target (§6.5).
"""

from jarvis.policy import Tier, ToolSpec, register

FILE_TOOLS = (
    ToolSpec("files.search", Tier.T0, walks_tree=True),
    ToolSpec("files.open", Tier.T0, target_key="path"),
    ToolSpec("files.reveal", Tier.T0, target_key="path"),
    ToolSpec("files.copy", Tier.T1, target_key="paths", walks_tree=True),
    ToolSpec("files.zip", Tier.T1, target_key="paths", walks_tree=True),
    ToolSpec("files.move", Tier.T2, undoable=True, target_key="paths", walks_tree=True),
    ToolSpec("files.rename", Tier.T2, undoable=True, target_key="path"),
    ToolSpec("files.trash", Tier.T2, undoable=True, target_key="paths", walks_tree=True),
    ToolSpec("files.delete_permanently", Tier.T3, target_key="paths", walks_tree=True),
)

for _spec in FILE_TOOLS:
    register(_spec)
