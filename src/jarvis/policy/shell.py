"""Classify a shell command line into a risk tier and consent scopes (FRS 5.10, R84).

Fail closed: anything not recognised as safe is T2, and a command that cannot be parsed is
never T0.
"""

import os
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar

from jarvis.config import DEFAULT_CONSENT_FOLDERS
from jarvis.policy.hidden import inner_commands
from jarvis.policy.lists import is_under, real_path
from jarvis.policy.model import Tier


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# A command line longer than this is not read at all; the work on shorter ones is budgeted too,
# so no input can make the (uncancellable) classification run long.
MAX_COMMAND_LENGTH = 4096
_BUDGET_UNITS = 3 * MAX_COMMAND_LENGTH
_MAX_WORDS_FOR_SCOPES = 128
_ACCESS = ("read", "write")
TOO_LONG_REASON = "too long to check"
TOO_COMPLEX_REASON = "too complex to check"
_budget: ContextVar[list[int] | None] = ContextVar("shell_budget", default=None)


class _OutOfBudget(Exception):
    """The classification used up its work budget."""


def _charge(units: int) -> None:
    """Spend work units; running out ends the whole classification as T3."""
    remaining = _budget.get()
    if remaining is not None:
        remaining[0] -= units
        if remaining[0] < 0:
            raise _OutOfBudget


_SHELLS = _words("sh bash zsh dash ksh fish")
_ALWAYS_T3 = _words(
    "sudo doas pkexec su format diskpart shutdown reboot poweroff halt shred wipefs"
)
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
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# Words that run what follows them; skipped to find the command that really runs.
_WRAPPERS = _words("env command nohup time exec nice xargs timeout setsid unbuffer stdbuf ionice")
_WRAPPERS |= _words("busybox flock watch chroot taskset chrt nsenter unshare setpriv runuser")
_WRAPPERS |= _words("if then do else elif while until ! { }")
_FORK_BOMB = ":(){:|:&};:"
_INTERPRETER = re.compile(r"python[0-9.]*|perl|ruby|nodejs|node|php|lua")
# The flag that hands an interpreter its program text, per language (R94).
_CODE_FLAG = re.compile(
    r"python[0-9.]*:-[A-Za-z]*c|perl:-[A-Za-z]*[eE]|ruby:-[A-Za-z]*e|node(?:js)?:(?:-[ep]|--eval|--print)"
    r"|php:-r|lua:-e"
)
_DESTRUCTIVE_CODE = re.compile(
    r"rmtree|os\.(?:remove|rmdir|unlink|removedirs)|unlink|removedirs|rmSync|rimraf"
    r"|\brm\s+-[A-Za-z]*[rRfF]|\brm\s+--(?:recursive|force)|\bshred\b"
)
_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_DELETERS = frozenset({"rm", "rmdir", "shred", "unlink"})
_STOPPING = frozenset({"stop", "disable", "mask"})
_UNPARSEABLE_T3 = _words("sudo doas pkexec shutdown reboot poweroff")


def _is_operator(token: str) -> bool:
    """A token made only of shell punctuation: `|`, `&&`, `;`, `>|`, `<(` ..."""
    return bool(token) and set(token) <= _PUNCTUATION


def _is_redirect(token: str) -> bool:
    """A punctuation token that reads or writes: `>`, `>>`, `>|`, `<`, `<<<`, `<(`, `>(` ..."""
    return _is_operator(token) and bool(set(token) & {"<", ">"})


def _segments(cmd: str) -> tuple[list[list[str]], list[str], dict[int, str]]:
    """Split into command segments, the operator after each (`""` for the last) and here-docs.

    Redirections stay inside their segment, so `ls >| f` and `cat <(rm x)` keep every word.
    A here-document's body is not a command line: it is returned by segment index instead.
    """
    segments: list[list[str]] = []
    seps: list[str] = []
    docs: dict[int, str] = {}
    lines = cmd.splitlines()  # a newline ends a command, like `;`
    n = 0
    while n < len(lines):
        lexer = shlex.shlex(lines[n], posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        n += 1
        current: list[str] = []
        delimiter: tuple[int, str] | None = None
        for token in lexer:
            if current and current[-1] == "<<" and delimiter is None:
                delimiter = (len(segments), token)
            if not _is_operator(token) or _is_redirect(token):
                current.append(token)
            elif current:
                segments.append(current)
                seps.append(token)
                current = []
        if current:
            segments.append(current)
            seps.append(";")
        if delimiter is not None:
            body = []
            while n < len(lines) and lines[n].strip() != delimiter[1]:
                body.append(lines[n])
                n += 1
            n += 1
            docs[delimiter[0]] = "\n".join(body)
    if seps:
        seps[-1] = ""
    return segments, seps, docs


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
    """`sh -c TEXT` whose text is T3 or missing. Text that cannot be read is T3 (R94)."""
    for i, arg in enumerate(args):
        if _SHELL_C.fullmatch(arg):
            return i + 1 >= len(args) or _tier(args[i + 1], nested=True)[0] == Tier.T3
    return False


def _eval(args: list[str]) -> bool:
    return bool(args) and _tier(" ".join(args), nested=True)[0] == Tier.T3


def _reg(args: list[str]) -> bool:
    words = [a for a in args if not a.startswith(("-", "/"))]
    return bool(words) and words[0].lower() == "delete"


def _del(args: list[str]) -> bool:
    return any(a.lower() == "/s" for a in args)


def _is_root(resolved: str) -> bool:
    """A filesystem root: `/` (or `C:\\` on Windows)."""
    return os.path.dirname(resolved) == resolved


def _is_home_or_root(path: str) -> bool:
    resolved = real_path(path)
    return _is_root(resolved) or resolved == real_path("~")


def _is_top_level(path: str) -> bool:
    """Home, a root, or a directory directly under one (/etc)."""
    return _is_home_or_root(path) or _is_root(os.path.dirname(real_path(path)))


def _chperm(args: list[str]) -> bool:
    """`chmod`/`chown` of `/` or home, or recursively of `/*`."""
    return _chmod(args) or any(_is_home_or_root(word) for word in _flags(args)[1])


def _mv(args: list[str]) -> bool:
    """`mv` of home, `/` or a top-level directory (a variable could be any of them)."""
    flags, words = _flags(args)
    if "-t" in flags:
        words = words[1:]  # `-t DIR` names the destination, not a source
    return any("$" in word or "`" in word or _is_top_level(word) for word in words)


def _find(args: list[str]) -> bool:
    """`find … -delete`, or `-exec rm` (and friends)."""
    if "-delete" in args:
        return True
    return any(
        arg in _EXEC_FLAGS and os.path.basename(args[i + 1]).lower() in _DELETERS
        for i, arg in enumerate(args[:-1])
    )


def _git(args: list[str]) -> bool:
    """`git clean` that forces and removes directories or ignored files."""
    if "clean" not in args:
        return False
    flags = _flags(args[args.index("clean") + 1 :])[0]
    return bool(flags & {"-f", "--force"}) and bool(flags & {"-d", "-x", "-X"})


def _kill(args: list[str]) -> bool:
    """`kill`/`pkill` aimed at PID 1 or at every process (`-1`)."""
    return any(arg in {"1", "-1"} for arg in args)


def _firewall(args: list[str]) -> bool:
    return bool(_flags(args)[0] & {"-F", "--flush"}) or "flush" in args


def _interpreter_code(name: str, args: list[str]) -> bool:
    """An interpreter's inline program (`python -c`, `perl -e`...) that deletes files.

    A code flag with no program after it cannot be read, so it counts as destructive.
    """
    for i, arg in enumerate(args):
        if arg.startswith("-") and _CODE_FLAG.fullmatch(f"{name}:{arg}"):
            return i + 1 >= len(args) or bool(_DESTRUCTIVE_CODE.search(args[i + 1]))
    return False


_T3_CHECKS: dict[str, Callable[[list[str]], bool]] = {
    "rm": _rm,
    "chmod": _chperm,
    "chown": _chperm,
    "mv": _mv,
    "find": _find,
    "git": _git,
    "crontab": lambda args: "-r" in _flags(args)[0],
    "kill": _kill,
    "pkill": _kill,
    "killall": _kill,
    "systemctl": lambda args: bool(_STOPPING & set(args)),
    "ufw": lambda args: "disable" in args,
    "setenforce": lambda args: bool({"0", "permissive"} & {a.lower() for a in args}),
    "iptables": _firewall,
    "ip6tables": _firewall,
    "nft": _firewall,
    "dd": lambda args: any(a.startswith("of=/dev/") for a in args),
    "reg": _reg,
    "del": _del,
    "erase": _del,
    "set-executionpolicy": lambda args: True,
}
# Checks that classify text again. They run only where a command may start (after wrappers), so
# `eval eval eval ...` is read once per level and not once per word.
_NESTED_CHECKS: dict[str, Callable[[list[str]], bool]] = {
    "eval": _eval,
    **dict.fromkeys(_SHELLS, _shell_c),
}


def _head(seg: list[str]) -> str | None:
    """The command that really runs: past assignments, wrappers and their flags and numbers."""
    for token in seg:
        skip = _ASSIGNMENT.match(token) or token.startswith("-") or token.isdigit()
        if not skip and os.path.basename(token).lower() not in _WRAPPERS:
            return token
    return None


def _reads_program(head: str | None) -> bool:
    """A shell or an interpreter: it runs whatever text it is given."""
    name = os.path.basename(head or "").lower()
    return name in _SHELLS or bool(_INTERPRETER.fullmatch(name))


def _computed(head: str) -> bool:
    """A command name made at run time: `$X`, `$(…)`, `"`…`"`, a glob or a brace."""
    if head in {"[[", "]]", "[", "{", "}"}:
        return False
    return bool(re.search(r"[$`*?]|[\[{].*[\]}]", head))


def _program_text_t3(seg: list[str], head: str, doc: str | None) -> bool:
    """A shell or interpreter fed text by `<<<` or a here-doc: T3 if it deletes or is lost."""
    shell = os.path.basename(head).lower() in _SHELLS
    texts: list[str | None] = [
        seg[i + 1] if i + 1 < len(seg) else None for i, t in enumerate(seg) if t == "<<<"
    ]
    if "<<" in seg:
        texts.append(doc)
    for text in texts:
        if text is None:
            return True
        if shell and _tier(text, nested=True)[0] == Tier.T3:
            return True
        if not shell and _DESTRUCTIVE_CODE.search(text):
            return True
    return False


def _wrapperish(token: str, name: str) -> bool:
    """A word that may sit before the real command: a wrapper, an option, a number, a path."""
    return bool(
        _ASSIGNMENT.match(token)
        or token.startswith("-")
        or token.isdigit()
        or "/" in token
        or name in _WRAPPERS
    )


def _t3_at(seg: list[str], pos: int, name: str, may_start: bool) -> bool:
    """Whether the word at `pos`, taken as a command name, makes the segment T3."""
    if name in _ALWAYS_T3 or name.startswith("mkfs"):
        return True
    nested = _NESTED_CHECKS.get(name) if may_start else None
    check = nested or _T3_CHECKS.get(name)
    interpreter = bool(_INTERPRETER.fullmatch(name))
    if check is None and not interpreter:
        return False
    args = seg[pos + 1 :]  # sliced only for a word that names a checked command
    _charge(len(args) + 1)
    return bool(check and check(args)) or (interpreter and _interpreter_code(name, args))


def _is_t3(segments: list[list[str]], seps: list[str], docs: dict[int, str]) -> bool:
    for i, seg in enumerate(segments):
        may_start = True  # every word before this one is a wrapper, option, number or path
        for pos, token in enumerate(seg):
            name = os.path.basename(token).lower()
            # A word with a `/` is a path (`cat ~/notes/su`), a command only where one may start.
            if ("/" not in token or may_start) and _t3_at(seg, pos, name, may_start):
                return True
            may_start = may_start and _wrapperish(token, name)
        head = _head(seg)
        if head is not None:
            if _computed(head):
                return True
            if _reads_program(head) and _program_text_t3(seg, head, docs.get(i)):
                return True
        if seps[i] in {"|", "|&"} and _reads_program(_head(segments[i + 1])):
            return True  # a pipe into a shell or interpreter runs unseen text, decoded or not
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
    checks = [(seg, _T0_ARGS.get(seg[0], _any_args)) for seg in segments]
    return all(seg[0] in _T0 and check(seg[1:]) for seg, check in checks)


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


def _tier(cmd: str, *, nested: bool) -> tuple[Tier, list[list[str]]]:
    """The tier of `cmd` and its segments. `nested` text (inside `eval`, `$(…)`) must parse."""
    _charge(len(cmd) + 1)
    if _FORK_BOMB in re.sub(r"\s+", "", cmd):
        return Tier.T3, []
    inner = inner_commands(cmd)
    if inner is None:  # a substitution that never closes
        return Tier.T3, []
    try:
        segments, seps, docs = _segments(cmd)
    except ValueError:  # unbalanced quote: T2, or T3 when a dangerous word is plainly there
        unreadable = nested or bool(set(cmd.split()) & _UNPARSEABLE_T3)
        return (Tier.T3 if unreadable else Tier.T2), []
    if _is_t3(segments, seps, docs) or any(_tier(t, nested=True)[0] == Tier.T3 for t in inner):
        return Tier.T3, segments
    if not segments or inner or not _is_t0(cmd, segments, seps):
        return Tier.T2, segments
    return Tier.T0, segments


def _run(cmd: str) -> tuple[Tier, list[list[str]], str]:
    """Classify within the length cap and the work budget; the reason is set when they bite."""
    if len(cmd) > MAX_COMMAND_LENGTH:
        return Tier.T3, [], TOO_LONG_REASON
    token = _budget.set([_BUDGET_UNITS])
    try:
        tier, segments = _tier(cmd, nested=False)
    except _OutOfBudget:
        return Tier.T3, [], TOO_COMPLEX_REASON
    finally:
        _budget.reset(token)
    return tier, segments, ""


def shell_limit_reason(cmd: str) -> str:
    """ "too long to check" or "too complex to check" when `cmd` is T3 for that reason, else ""."""
    return _run(cmd)[2]


def classify_shell(
    cmd: str,
    *,
    folders: Mapping[str, str] = DEFAULT_CONSENT_FOLDERS,
    allow: Sequence[str] = (),
) -> tuple[Tier, tuple[str, ...]]:
    """Return the tier of a shell command line and the consent scopes its paths touch."""
    tier, segments, _ = _run(cmd)
    if sum(len(seg) for seg in segments) > _MAX_WORDS_FOR_SCOPES:
        # Too many words to resolve one by one (each is a filesystem lookup): assume the worst.
        return tier, tuple(sorted(f"{src}:{mode}" for src in folders.values() for mode in _ACCESS))
    return tier, _scopes(segments, folders, allow)
