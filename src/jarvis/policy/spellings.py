"""The many ways a flag can be written: separate word, `=` form, attached to its value (F2, R99)."""

import re

# Per interpreter family: the short flags that take a program, and the ones that take some
# other value (so the rest of the word is that value, not more flags).
_PROGRAM_FLAGS = {
    "python": ("c", "mWX"),
    "perl": ("eE", "IMm"),
    "ruby": ("e", "IrCEx"),
    "node": ("ep", "r"),
    "php": ("r", "dcfz"),
    "lua": ("e", "l"),
    "osascript": ("e", "l"),
}
_LONG_PROGRAM = frozenset({"--command", "--eval", "--print"})
_POWERSHELL = ("-command", "-encodedcommand", "-ec")  # -ec is an alias, not a prefix


def _family(name: str) -> str:
    if name.startswith("python"):
        return "python"
    return "node" if name.startswith("node") else name


def code_flag(name: str, arg: str) -> bool:
    """Whether `arg` hands interpreter `name` a program: `-c`, `-cCODE`, `-Ic`, `--eval=...`."""
    if name.startswith(("pwsh", "powershell")):
        flag = arg.lower().split(":", 1)[0]
        return len(flag) >= 2 and flag[0] == "-" and any(c.startswith(flag) for c in _POWERSHELL)
    if arg.startswith("--"):
        return arg.split("=", 1)[0] in _LONG_PROGRAM
    if not arg.startswith("-") or len(arg) < 2:
        return False
    program, value_flags = _PROGRAM_FLAGS.get(_family(name), ("", ""))
    for char in arg[1:]:
        if char in program:
            return True
        if char in value_flags:
            return False  # the rest of the word is that flag's value
    return False


def target_dirs(args: list[str]) -> list[str]:
    """The values of `-t`/`--target-directory`, however written (`-t D`, `-tD`, `-at D`, `=D`)."""
    found: list[str] = []
    for i, arg in enumerate(args):
        following = args[i + 1 : i + 2]
        if arg == "--target-directory":
            found += following
        elif arg.startswith("--target-directory="):
            found.append(arg.split("=", 1)[1])
        elif arg.startswith("-") and not arg.startswith("--") and "t" in arg[1:]:
            cut = arg.index("t", 1)
            found += [arg[cut + 1 :]] if arg[cut + 1 :] else following
    return found


def sed_in_place(args: list[str]) -> bool:
    """`sed -i[SUFFIX]`, `-ni`, `--in-place[=SUFFIX]`."""
    return any(
        a == "--in-place"
        or a.startswith("--in-place=")
        or (a.startswith("-") and not a.startswith("--") and "i" in a[1:])
        for a in args
    )


def crontab_installs(args: list[str]) -> bool:
    """`crontab FILE` and `crontab -` replace the crontab; `crontab -l` only reads it."""
    flags = {a for a in args if a.startswith("-") and len(a) > 1}
    words = [a for a in args if not a.startswith("-") or a == "-"]
    if "-u" in args:  # `crontab -u USER`: the user is a word, not a file
        words = [w for i, w in enumerate(args) if w in words and args[i - 1] != "-u"]
    return "-l" not in flags and bool(words)


_AWK_RISK = re.compile(r"system\s*\(|\||>")
_AWK_VALUED = frozenset({"-F", "-v", "-f", "--field-separator", "--assign", "--file"})


def awk_program_unsafe(args: list[str]) -> bool:
    """An awk program whose text can run a command or write a file: `system(`, `|`, `>`."""
    skip = False
    program_next = False
    for arg in args:
        if skip:
            skip = False
        elif program_next:
            return bool(_AWK_RISK.search(arg))
        elif arg in {"-e", "--source"}:
            program_next = True
        elif arg in _AWK_VALUED:
            skip = True
        elif arg.startswith("--source="):
            return bool(_AWK_RISK.search(arg.split("=", 1)[1]))
        elif not arg.startswith("-"):
            return bool(_AWK_RISK.search(arg))  # the first plain word is the program
    return False
