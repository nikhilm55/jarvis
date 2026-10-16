"""Classify a shell command line into a risk tier and consent scopes (FRS 5.10, R84).

Fail closed: anything not recognised as safe is T2, and a command that cannot be parsed is
never T0.
"""

import os
import re
import shlex
from collections.abc import Callable, Mapping, Sequence

from jarvis.config import DEFAULT_CONSENT_FOLDERS
from jarvis.policy.lists import is_under, real_path
from jarvis.policy.model import Tier


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_SHELLS = _words("sh bash zsh dash ksh fish")
_ALWAYS_T3 = _words("sudo doas pkexec format diskpart shutdown reboot poweroff halt")
_T0 = _words("ls cat head tail wc pwd df du ps uptime which echo date whoami git")
_READ = _words("ls cat head tail wc pwd git du df ps which date whoami")
_GIT_SUBS = _words("status log diff branch show")
_GIT_BRANCH_OK = _words("-a -r -v -vv --list --show-current --all --remotes")
# Characters that can chain, nest, redirect or expand: a T0 line holds none (`|` and a bare `<`
# are checked per token, because a plain pipe between reads and `< file` stay T0).
_UNSAFE_FOR_T0 = frozenset("`$();>&\n\r")
_PUNCTUATION = frozenset("();<>|&")
# Safe `git` options for the T0 subcommands, as whole-option prefixes. Anything else is refused,
# so an abbreviated writing option (`--outp=f`) cannot slip through a denylist.
_GIT_SAFE_OPTS = [
    "--oneline",
    "--stat",
    "--shortstat",
    "--numstat",
    "--name-only",
    "--name-status",
    "--format",
    "--pretty",
    "--graph",
    "--decorate",
    "--no-decorate",
    "--abbrev-commit",
    "--abbrev",
    "--short",
    "--branch",
    "--porcelain",
    "--no-color",
    "--color",
    "--since",
    "--until",
    "--author",
    "--grep",
    "--all",
    "--cached",
    "--staged",
    "--summary",
    "--patch",
    "--no-patch",
    "--no-merges",
    "--merges",
    "--first-parent",
    "--reverse",
    "--date",
    "--max-count",
    "--no-pager",
]
_GIT_SAFE_SHORT = re.compile(r"-(?:[0-9]+|[nsbpuvq]|U[0-9]+|n[0-9]+)")
_SHELL_C = re.compile(r"-[a-z]*c[a-z]*")
_RECURSIVE = re.compile(r"-[A-Za-z]*R[A-Za-z]*|--recursive")
_FORK_BOMB = ":(){:|:&};:"
_UNPARSEABLE_T3 = _words("sudo doas pkexec shutdown reboot poweroff")


def _is_operator(token: str) -> bool:
    """A token made only of shell punctuation: `|`, `&&`, `;`, `>|`, `<(` ..."""
    return bool(token) and set(token) <= _PUNCTUATION


def _is_redirect(token: str) -> bool:
    """A punctuation token that reads or writes: `>`, `>>`, `>|`, `<`, `<<<`, `<(`, `>(` ..."""
    return _is_operator(token) and bool(set(token) & {"<", ">"})


def _segments(cmd: str) -> tuple[list[list[str]], list[str]]:
    """Split into command segments plus the operator that follows each (`""` for the last).

    Redirections stay inside their segment, so `ls >| f` and `cat <(rm x)` keep every word.
    """
    segments: list[list[str]] = []
    seps: list[str] = []
    for line in cmd.splitlines():  # a newline ends a command, like `;`
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        current: list[str] = []
        for token in lexer:
            if not _is_operator(token) or _is_redirect(token):
                current.append(token)
            elif current:
                segments.append(current)
                seps.append(token)
                current = []
        if current:
            segments.append(current)
            seps.append(";")
    if seps:
        seps[-1] = ""
    return segments, seps


def _names(seg: list[str]) -> set[str]:
    """The lower-case base name of every token of `seg`: any of them may be the real command."""
    return {os.path.basename(token).lower() for token in seg}


def _flags(args: list[str]) -> tuple[set[str], list[str]]:
    """Split args into single-letter and long flags plus positional words (`--` ends flags)."""
    flags: set[str] = set()
    words: list[str] = []
    for i, arg in enumerate(args):
        if arg == "--":
            words += args[i + 1 :]
            break
        if arg.startswith("--"):
            flags.add(arg)
        elif arg.startswith("-") and len(arg) > 1:
            flags.update(f"-{c}" for c in arg[1:])
        else:
            words.append(arg)
    return flags, words


def _in_tmp(path: str) -> bool:
    """True when `path` is strictly inside /tmp or $TMPDIR (symlinks and `..` resolved)."""
    tmpdir = os.environ.get("TMPDIR", "")
    if tmpdir and path.startswith("$TMPDIR"):
        path = tmpdir + path[len("$TMPDIR") :]
    if "$" in path or "~" in path:
        return False
    roots = [os.path.realpath("/tmp")] + ([os.path.realpath(tmpdir)] if tmpdir else [])  # noqa: S108
    real = real_path(path)  # a relative path is relative to home, where the shell runs (R84)
    return any(real.startswith(root.rstrip("/") + "/") for root in roots)


def _rm(args: list[str]) -> bool:
    flags, paths = _flags(args)
    if not (flags & {"-r", "-R", "--recursive"} and flags & {"-f", "--force"}):
        return False
    return not paths or not all(_in_tmp(p) for p in paths)


def _chmod(args: list[str]) -> bool:
    return any(_RECURSIVE.fullmatch(a) for a in args) and any(a in {"/", "/*"} for a in args)


def _shell_c(args: list[str]) -> bool:
    for i, arg in enumerate(args[:-1]):
        if _SHELL_C.fullmatch(arg):
            return classify_shell(args[i + 1])[0] == Tier.T3
    return False


def _reg(args: list[str]) -> bool:
    words = [a for a in args if not a.startswith(("-", "/"))]
    return bool(words) and words[0].lower() == "delete"


def _del(args: list[str]) -> bool:
    return any(a.lower() == "/s" for a in args)


_T3_CHECKS: dict[str, Callable[[list[str]], bool]] = {
    "rm": _rm,
    "chmod": _chmod,
    "chown": _chmod,
    "dd": lambda args: any(a.startswith("of=/dev/") for a in args),
    "reg": _reg,
    "del": _del,
    "erase": _del,
    "set-executionpolicy": lambda args: True,
    **dict.fromkeys(_SHELLS, _shell_c),
}


def _pipes_to_shell(left: list[str], right: list[str]) -> bool:
    return bool(_names(left) & {"curl", "wget"}) and bool(_names(right) & _SHELLS)


def _is_t3(segments: list[list[str]], seps: list[str]) -> bool:
    for i, seg in enumerate(segments):
        for pos, token in enumerate(seg):  # every position: wrappers, `cat <(rm x)`, `if`, `time`
            name = os.path.basename(token).lower()
            check = _T3_CHECKS.get(name)
            if name in _ALWAYS_T3 or name.startswith("mkfs") or (check and check(seg[pos + 1 :])):
                return True
        if seps[i] == "|" and _pipes_to_shell(seg, segments[i + 1]):
            return True
    return False


def _git_option_ok(arg: str) -> bool:
    if arg == "--" or not arg.startswith("-"):
        return True
    return arg.startswith(tuple(_GIT_SAFE_OPTS)) or bool(_GIT_SAFE_SHORT.fullmatch(arg))


def _git_t0(args: list[str]) -> bool:
    if not args or args[0] not in _GIT_SUBS:
        return False
    if args[0] == "branch":
        return all(a in _GIT_BRANCH_OK for a in args[1:])
    return all(_git_option_ok(a) for a in args[1:])


def _date_t0(args: list[str]) -> bool:
    """`date` alone or with one `+FORMAT`; every other option could set the clock."""
    return not args or (len(args) == 1 and args[0].startswith("+"))


_T0_ARGS: dict[str, Callable[[list[str]], bool]] = {"git": _git_t0, "date": _date_t0}


def _any_args(args: list[str]) -> bool:
    return True


def _is_t0(cmd: str, segments: list[list[str]], seps: list[str]) -> bool:
    if _UNSAFE_FOR_T0 & set(cmd) or any(sep not in ("", "|") for sep in seps):
        return False
    if any(_is_redirect(t) and t != "<" for seg in segments for t in seg):
        return False
    # The bare first token: no path (`./ls`), no assignment (`FOO=1 ls`), no wrapper.
    return all(seg[0] in _T0 and _T0_ARGS.get(seg[0], _any_args)(seg[1:]) for seg in segments)


def _scopes(
    segments: list[list[str]], folders: Mapping[str, str], allow: Sequence[str]
) -> tuple[str, ...]:
    roots = [(real_path(folder), source) for folder, source in folders.items()]
    exempt = [real_path(path) for path in allow]
    found: set[str] = set()
    for seg in segments:
        read = os.path.basename(seg[0]) in _READ
        pending: str | None = None  # the access a redirection gives the token after it
        for i, token in enumerate(seg):
            if _is_redirect(token):
                pending = "write" if ">" in token else "read"
                continue
            mode, pending = pending, None
            if mode is None:
                if i == 0 or token.startswith("-") or seg[0] == "echo":
                    continue
                mode = "read" if read else "write"
            path = real_path(token)
            if not any(is_under(path, e) for e in exempt):
                found.update(f"{source}:{mode}" for root, source in roots if is_under(path, root))
    return tuple(sorted(found))


def classify_shell(
    cmd: str,
    *,
    folders: Mapping[str, str] = DEFAULT_CONSENT_FOLDERS,
    allow: Sequence[str] = (),
) -> tuple[Tier, tuple[str, ...]]:
    """Return the tier of a shell command line and the consent scopes its paths touch."""
    if _FORK_BOMB in re.sub(r"\s+", "", cmd):
        return Tier.T3, ()
    try:
        segments, seps = _segments(cmd)
    except ValueError:  # unbalanced quote: T2, or T3 when a dangerous word is plainly there
        return (Tier.T3 if set(cmd.split()) & _UNPARSEABLE_T3 else Tier.T2), ()
    if not segments:
        return Tier.T2, ()
    scopes = _scopes(segments, folders, allow)
    if _is_t3(segments, seps):
        return Tier.T3, scopes
    return (Tier.T0 if _is_t0(cmd, segments, seps) else Tier.T2), scopes
