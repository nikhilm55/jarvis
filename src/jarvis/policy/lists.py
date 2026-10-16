"""Deny/allow lists (FR-SAFE-09): which paths and commands a call touches."""

import glob
import os
import re
import shlex
from collections.abc import Mapping

from jarvis.config import PolicySettings

_PATH_KEYS = frozenset(
    {"path", "paths", "file", "files", "src", "dst", "source", "dest", "destination"}
    | {"dir", "directory", "folder", "target", "cwd"}
)
_COMMAND_KEYS = ("cmd", "command")
_OPERATORS = re.compile(r"[<>|&;()`]")


def real_path(path: str) -> str:
    """Resolve `~`, `$HOME` and relative paths (against home) through symlinks."""
    path = re.sub(r"^\$(?:HOME\b|\{HOME\})", "~", path)
    return os.path.realpath(os.path.join(os.path.expanduser("~"), os.path.expanduser(path)))


def is_under(path: str, root: str) -> bool:
    """True when `path` is `root` or inside it (both already resolved)."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def command_of(args: Mapping[str, object]) -> str:
    """The shell command line in `args`, or "" when the call has none."""
    return next((v for k in _COMMAND_KEYS if isinstance(v := args.get(k), str)), "")


def _shell_paths(cmd: str) -> list[str]:
    """Every word of a command line that could be a path (more than needed: fail closed)."""
    text = _OPERATORS.sub(" ", cmd)
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    paths = [w for w in words if not w.startswith("-")]
    paths += [w.split("=", 1)[1] for w in words if "=" in w]  # `--out=/x`, `FOO=/x`
    return paths


def path_args(args: Mapping[str, object]) -> list[str]:
    """The path-like arguments of a call: path-named keys plus the words of a shell command."""
    paths: list[str] = []
    for key, value in args.items():
        if key in _PATH_KEYS:
            paths += _strings(value)
    return paths + _shell_paths(command_of(args))


def _resolved(path: str) -> list[str]:
    """A path resolved; a glob resolves to every match plus the pattern itself."""
    found = [real_path(path)]
    if any(c in path for c in "*?["):
        found += [real_path(m) for m in glob.glob(os.path.expanduser(path))]
    return found


def denied(args: Mapping[str, object], settings: PolicySettings) -> str | None:
    """The reason a call is on the deny list, or None. A deny entry beats every tier."""
    cmd = command_of(args)
    for pattern in settings.deny_commands:
        if cmd and re.search(pattern, cmd):
            return f"denied: the command matches the deny list ({pattern!r})"
    roots = [real_path(p) for p in settings.deny_paths]
    for path in path_args(args):
        if any(is_under(r, root) for r in _resolved(path) for root in roots):
            return f"denied: {path} is on the deny list"
    return None


def path_scopes(
    args: Mapping[str, object], access: str, settings: PolicySettings
) -> tuple[str, ...]:
    """Consent scopes for the path-named arguments (a shell command maps its own, R84)."""
    folders = [(real_path(f), src) for f, src in settings.consent_folders.items()]
    exempt = [real_path(p) for p in settings.allow_paths]
    paths = [p for k, v in args.items() if k in _PATH_KEYS for p in _strings(v)]
    scopes = {
        f"{src}:{access}"
        for path in map(real_path, paths)
        if not any(is_under(path, e) for e in exempt)
        for root, src in folders
        if is_under(path, root)
    }
    return tuple(sorted(scopes))
