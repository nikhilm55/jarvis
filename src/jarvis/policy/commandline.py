"""What a command line does to the directory it runs in, and which commands walk a tree (N2)."""

import os
import re
import shlex

DIR_CHANGES = frozenset({"cd", "pushd", "popd"})
_DIR_LONG = ("--directory", "--chdir", "--cwd")
# Commands that read, copy, move or change everything under the directories they are given.
_ALWAYS_RECURSIVE = frozenset(
    [
        "rsync",
        "tar",
        "zip",
        "unzip",
        "7z",
        "7za",
        "7zr",
        "find",
        "du",
        "tree",
        "rg",
        "ag",
        "ack",
        "mv",
        "scp",
        "ditto",
    ]
)
_RECURSIVE_FLAGS: dict[str, frozenset[str]] = {
    "cp": frozenset({"-r", "-R", "-a", "--recursive", "--archive"}),
    "rm": frozenset({"-r", "-R", "--recursive"}),
    "ls": frozenset({"-R", "--recursive"}),
    "chmod": frozenset({"-R", "--recursive"}),
    "chown": frozenset({"-R", "--recursive"}),
    "chgrp": frozenset({"-R", "--recursive"}),
    "grep": frozenset({"-r", "-R", "--recursive", "--dereference-recursive"}),
    "egrep": frozenset({"-r", "-R", "--recursive"}),
    "fgrep": frozenset({"-r", "-R", "--recursive"}),
}
# A string with one of these as its first word is read as a command line, whatever its key.
_KNOWN = (
    _ALWAYS_RECURSIVE
    | DIR_CHANGES
    | frozenset(_RECURSIVE_FLAGS)
    | frozenset(
        [
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
        ]
    )
    | frozenset(
        [
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


def _flag_set(words: list[str]) -> set[str]:
    flags: set[str] = set()
    for word in words:
        if word.startswith("--"):
            flags.add(word.split("=", 1)[0])
        elif word.startswith("-") and len(word) > 1:
            flags.update(f"-{c}" for c in word[1:])
    return flags


def tree_walkers(text: str) -> list[list[str]]:
    """For each command of `text` that walks a whole tree, its non-option words (the paths)."""
    found: list[list[str]] = []
    for part in _SPLIT.split(text):
        words = words_of(part)
        for i, word in enumerate(words or []):
            name = os.path.basename(word)
            rest = (words or [])[i + 1 :]
            recursive = name in _ALWAYS_RECURSIVE or bool(
                _RECURSIVE_FLAGS.get(name, frozenset()) & _flag_set(rest)
            )
            if recursive:
                found.append([w for w in rest if not w.startswith("-")])
    return found
