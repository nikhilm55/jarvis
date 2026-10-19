"""What a command line does to the directory it runs in, and which commands walk a tree (N2)."""

import os
import re
import shlex

DIR_CHANGES = frozenset({"cd", "pushd", "popd"})
_DIR_LONG = ("--directory", "--chdir", "--cwd")
# Commands that only look, never walk: the one place a parent of a protected folder may appear.
READ_ONLY = frozenset(
    ["ls", "stat", "file", "test", "[", "realpath", "readlink", "basename", "dirname"]
)
# A string with one of these as its first word is read as a command line, whatever its key.
_KNOWN = frozenset(
    [
        "cd",
        "pushd",
        "popd",
        "cp",
        "rm",
        "ls",
        "mv",
        "rsync",
        "tar",
        "zip",
        "unzip",
        "7z",
        "find",
        "du",
        "tree",
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "chmod",
        "chown",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "tee",
        "sed",
        "awk",
        "echo",
        "curl",
        "wget",
        "env",
        "sudo",
        "xargs",
        "git",
        "make",
        "ln",
        "mount",
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "fish",
        "eval",
        "source",
        "python",
        "python3",
        "perl",
        "ruby",
        "node",
    ]
)
_SPLIT = re.compile(r"[;&|\n]+")


def words_of(text: str) -> list[str] | None:
    """The shell words of `text`, operators read as spaces; None when it cannot be parsed."""
    try:
        return shlex.split(re.sub(r"[<>|&;()`]", " ", text))
    except ValueError:
        return None


def dir_changes(words: list[str]) -> list[str]:
    """The directories a command line moves into: `cd D`, `-C D`, `-CD`, `--directory[=]D`..."""
    found: list[str] = []
    for i, word in enumerate(words):
        following = words[i + 1] if i + 1 < len(words) else ""
        if word in DIR_CHANGES or word == "-C" or word in _DIR_LONG:
            found.append(following)
        elif word.startswith("-C") and not word.startswith("--"):
            found.append(word[2:])
        elif word.startswith(tuple(f"{flag}=" for flag in _DIR_LONG)):
            found.append(word.split("=", 1)[1])
    return found


def command_like(text: str) -> bool:
    """A string that reads as a shell line holding a known command (under any argument key)."""
    words = words_of(text)
    return bool(words) and any(os.path.basename(w) in _KNOWN for w in words or [])


def lists_a_tree(words: list[str]) -> bool:
    """`ls -R` and `ls --recursive`: not a plain look."""
    return any(
        w == "--recursive" or (w.startswith("-") and not w.startswith("--") and "R" in w)
        for w in words
    )


def read_only(segment: str) -> bool:
    """A command of the read-only allowlist (and `ls` without `-R`): it names, never walks."""
    words = words_of(segment) or []
    if not words:
        return False
    name = os.path.basename(words[0])
    return name in READ_ONLY and not (name == "ls" and lists_a_tree(words[1:]))
