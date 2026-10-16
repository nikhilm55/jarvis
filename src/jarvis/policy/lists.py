"""Deny/allow lists (FR-SAFE-09): which paths and commands a call touches."""

import glob
import os
import posixpath
import re
import shlex
from collections.abc import Mapping

from jarvis.config import PolicySettings
from jarvis.policy.commandline import command_like, dir_changes, tree_walkers

_PATH_KEYS = frozenset(
    {"path", "paths", "file", "files", "src", "dst", "source", "dest", "destination"}
    | {"dir", "directory", "folder", "target", "cwd"}
)
_COMMAND_KEYS = ("cmd", "command")
_OPERATORS = re.compile(r"[<>|&;()`]")


def real_path(path: str, base: str | None = None) -> str:
    """Resolve `~`, `$HOME` and relative paths through symlinks.

    A relative path is relative to `base` (a directory the command line moved into), else to
    home, where the shell tool runs (R84).
    """
    path = re.sub(r"^\$(?:HOME\b|\{HOME\})", "~", path)
    start = real_path(base) if base else os.path.expanduser("~")
    return os.path.realpath(os.path.join(start, os.path.expanduser(path)))


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
    paths += [w[2:] for w in words if re.match(r"-[A-Za-z]", w) and len(w) > 2]  # `-Cdir`, `-fx`
    return paths


_LEADING = frozenset({"sudo", "doas", "env", "nohup", "time", "nice", "command", "exec"})


def shell_targets(cmd: str) -> tuple[str, list[str]]:
    """The command and the non-option words after it, for a command line's last command."""
    last = [part for part in re.split(r"[;&|\n]+", cmd) if part.strip()][-1:]
    try:
        words = shlex.split(last[0]) if last else []
    except ValueError:
        words = last[0].split() if last else []
    words = [w for w in words if "=" not in w.split("/")[0] and os.path.basename(w) not in _LEADING]
    words = [w for w in words if not w.startswith("-") or w is words[0]]
    if not words:
        return "run", []
    return os.path.basename(words[0]), words[1:]


def speak_targets(verb: str, targets: list[str]) -> str:
    """ "confirm rm ~/a", "confirm rm 2 paths: ~/a, ~/b", or "confirm rm 5 paths in ~/x"."""
    names = [t.rstrip("/") or t for t in targets]
    if not names:
        return f"confirm {verb}"
    if len(names) == 1:
        return f"confirm {verb} {names[0]}"
    if len(names) <= 3:
        return f"confirm {verb} {len(names)} paths: {', '.join(names)}"
    parents = [posixpath.dirname(n) or "." for n in names]  # as the user wrote them, with `/`
    try:
        common = posixpath.commonpath(parents) or "."
    except ValueError:  # paths on different drives
        common = "several places"
    return f"confirm {verb} {len(names)} paths in {common}"


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


# Shown when the deny list is set and a call cannot be traced to the paths it touches (R96).
UNRESOLVABLE_REASON = (
    "denied: I can't tell whether that touches a protected folder; spell the path out"
)
_HOME_VAR = re.compile(r"\$(?:HOME\b|\{HOME\})")
_BRACES = re.compile(r"\{[^{}]*\}")
_FLAG_ATTACHED = re.compile(r"-[^-=\s][^=\s]*[/~]")  # `-C/dir`, `-f~/x`: a path glued to a flag
_MAX_DEPTH = 8


def _flatten(value: object, depth: int = 0) -> list[str] | None:
    """Every string inside `value` (lists, dicts, any depth); None when it nests too deeply."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        items = [*value.values(), *value.keys()]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        return []
    if depth >= _MAX_DEPTH:
        return None
    found: list[str] = []
    for item in items:
        inner = _flatten(item, depth + 1)
        if inner is None:
            return None
        found += inner
    return found


def _has_expansion(text: str) -> bool:
    """A variable (other than `$HOME`), substitution or brace expansion: its value is unknown."""
    clean = _HOME_VAR.sub("", text)
    return any(mark in clean for mark in ("$", "`", "<(", ">(")) or bool(_BRACES.search(clean))


def _cannot_resolve_command(cmd: str) -> bool:
    """A command line whose paths cannot all be read off it (R96)."""
    if _has_expansion(cmd):
        return True
    try:
        words = shlex.split(_OPERATORS.sub(" ", cmd))
    except ValueError:
        return True
    return bool(dir_changes(words)) or any(_FLAG_ATTACHED.match(w) for w in words)


def _unresolvable(args: Mapping[str, object], texts: list[str]) -> bool:
    for key in _COMMAND_KEYS:
        value = args.get(key)
        if isinstance(value, (list, tuple, Mapping, set)):
            return True  # a command given as a list or object is not a line we can read
        if isinstance(value, str) and _cannot_resolve_command(value):
            return True
    if any(_has_expansion(text) for key in _PATH_KEYS for text in _flatten(args.get(key)) or []):
        return True
    return any(command_like(t) and _cannot_resolve_command(t) for t in texts)  # under any key


def denied(args: Mapping[str, object], settings: PolicySettings) -> str | None:
    """The reason a call is on the deny list, or None. A deny entry beats every tier.

    With a deny list set, a call whose paths cannot be traced (variables, braces, `cd`, paths
    glued to flags, an unreadable line, over-deep arguments) is denied too: fail closed (R96).
    Every string argument, at any depth and under any key, is checked as a path.
    """
    if not (settings.deny_paths or settings.deny_commands):
        return None
    texts = _flatten(dict(args))
    if texts is None or _unresolvable(args, texts):
        return UNRESOLVABLE_REASON
    commands = [command_of(args), *(t for t in texts if command_like(t))]
    for pattern in settings.deny_commands:
        if any(re.search(pattern, c) for c in commands if c):
            return f"denied: the command matches the deny list ({pattern!r})"
    roots = [real_path(p) for p in settings.deny_paths]
    for text in texts:
        for path in [text, *_shell_paths(text)]:
            if any(is_under(r, root) for r in _resolved(path) for root in roots):
                return f"denied: {path} is on the deny list"
    for cmd in commands:  # a recursive command given a parent of a protected folder walks into it
        for path in (p for paths in tree_walkers(cmd) for p in paths):
            if any(is_under(root, r) for r in _resolved(path) for root in roots):
                return f"denied: {path} holds a protected folder and the command walks it"
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
