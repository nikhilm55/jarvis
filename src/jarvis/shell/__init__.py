"""The shell tool and its gate policy (R84, task 8): one command line, one classification.

`shell.run` is registered with a T0 base tier and a classifier, so the decided tier is
whatever `classify_shell` says (T0 allowlist, T2 everything else, T3 for the FR-SAFE-01
patterns and the R94-R99 checks) — the classifier may raise the tier, never lower it.
The command argument is `cmd`: the gate's `command_of` reads it for the YOLO target
phrase and the R96 unresolvable-command deny, and `provenance_keys=("cmd",)` keeps the
R83 rule that a brain-synthesised target gets confirmed.
"""

from collections.abc import Mapping

from jarvis.policy import Tier, ToolSpec, register
from jarvis.policy.shell import classify_shell
from jarvis.policy.shell import classify_shell as _classify_command


def _classify(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
    """The tier and scopes of the `cmd` argument; an unreadable command fails closed."""
    cmd = args.get("cmd")
    if not isinstance(cmd, str):
        return Tier.T3, ()
    return _classify_command(cmd)


SHELL_TOOLS = (
    ToolSpec(
        "shell.run",
        Tier.T0,
        classify=_classify,
        provenance_keys=("cmd",),
    ),
)

for _spec in SHELL_TOOLS:
    register(_spec)

__all__ = ["SHELL_TOOLS", "classify_shell"]
