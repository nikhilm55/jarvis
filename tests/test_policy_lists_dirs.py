"""N2: directory flags, tree-walking commands and command lines under any key (deny list)."""

import itertools
from pathlib import Path

import pytest

from jarvis.config import PolicySettings
from jarvis.policy.commandline import command_like, dir_changes, tree_walkers, words_of
from jarvis.policy.lists import denied
from jarvis.policy.shell import classify_shell

DENY = PolicySettings(deny_paths=["~/work/secrets"])


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "work" / "secrets").mkdir(parents=True)
    (tmp_path / "Documents").mkdir()
    return tmp_path


# Each of these reaches ~/work/secrets without naming it, or names its parent.
ESCAPES = [
    "tar -C ~/work -xf a.tar secrets/k",
    "tar -C ~/work -cf - secrets",
    "tar --directory ~/work -cf - secrets",
    "tar --directory=~/work -cf - secrets",
    "tar -cf - -Cwork secrets",
    "tar -C~/work -cf - secrets",
    "env -C ~/work cat secrets/k",
    "git -C ~/work show HEAD:secrets/k",
    "make -C ~/work secrets",
    "cmd --chdir ~/work cat secrets/k",
    "cmd --cwd=~/work cat secrets/k",
    "cd ~/work; cat secrets/k",
    "pushd ~/work && cat secrets/k",
    "cp -r ~/work /tmp/out",
    "cp -R ~/work /tmp/out",
    "cp -a ~/work /tmp/out",
    "tar -czf /tmp/a.tgz ~/work",
    "zip -r /tmp/a.zip ~/work",
    "7z a /tmp/a.7z ~/work",
    "rsync -a ~/work/ /tmp/out/",
    "find ~ -name k",
    "find / -name k",
    "grep -r token ~",
    "grep -R token ~/work",
    "du -a ~/work",
    "ls -R ~/work",
    "chmod -R 777 ~/work",
    "chown -R me ~/work",
    "rm -r ~/work",
    "mv ~/work /tmp/w",
    "rg token ~",
    "tree ~/work",
]


@pytest.mark.parametrize("line", ESCAPES)
@pytest.mark.parametrize("key", ["cmd", "command", "script", "text", "anything"])
def test_should_deny_the_escape_under_any_key_when_a_deny_list_is_set(line: str, key: str) -> None:
    assert denied({key: line}, DENY) is not None
    assert denied({key: line}, PolicySettings()) is None


@pytest.mark.parametrize("depth", [1, 2, 3])
@pytest.mark.parametrize("line", ESCAPES[::4])
def test_should_deny_the_escape_at_any_depth(line: str, depth: int) -> None:
    value: object = line
    for _ in range(depth):
        value = {"steps": [value]}
    assert denied({"plan": value}, DENY) is not None
    assert denied({"plan": value}, PolicySettings()) is None


@pytest.mark.parametrize("line", ["", "x"])
def test_should_run_the_property_over_every_escape_and_both_list_kinds(line: str) -> None:
    for escape, settings in itertools.product(
        ESCAPES, [DENY, PolicySettings(deny_paths=["~/work/secrets"], deny_commands=["^never$"])]
    ):
        assert denied({"cmd": f"{line} {escape}".strip()}, settings) is not None, escape


@pytest.mark.parametrize(
    "line",
    [
        "ls ~/work",
        "cat ~/work/notes.txt",
        "cp ~/work/a /tmp/a",
        "cp -r ~/Documents /tmp/d",
        "tar -czf /tmp/a.tgz ~/Documents",
        "grep -r token ~/Documents",
        "find ~/Documents -name k",
        "du -a ~/work/public",
        "git status",
        "echo cd is a command",
    ],
)
def test_should_keep_allowing_a_call_that_does_not_reach_the_protected_folder(line: str) -> None:
    reason = denied({"cmd": line}, DENY)
    # Only a bare `cd`/flag-like word in prose is refused (we cannot tell it from a real cd).
    assert reason is None or line.startswith("echo cd")


def test_should_find_the_directories_a_line_moves_into() -> None:
    words = words_of("cd a && tar -C b -x -Cc --directory d --chdir=e --cwd f git -C")
    assert words is not None
    assert dir_changes(words) == ["a", "b", "c", "d", "e", "f", ""]
    assert dir_changes(words_of("ls -la ~") or []) == []


def test_should_list_the_paths_of_each_tree_walking_command() -> None:
    assert tree_walkers("cp -r a b; ls -l c") == [["a", "b"]]
    assert tree_walkers("find x -name y | du z") == [["x", "y"], ["z"]]
    assert tree_walkers("cp a b") == []
    assert tree_walkers("grep pat f") == []
    assert tree_walkers("grep -rn pat d") == [["pat", "d"]]


def test_should_read_a_string_as_a_command_line_only_when_it_holds_a_known_command() -> None:
    assert command_like("cd ~/x && ls")
    assert command_like("/usr/bin/tar -xf a")
    assert not command_like("just some words")
    assert not command_like("~/secrets/key")
    assert not command_like("")


def test_should_resolve_a_directory_change_as_the_cwd_of_later_relative_paths(home: Path) -> None:
    assert classify_shell("cd ~/Documents && cat a")[1] == ("files.documents:read",)
    assert classify_shell("make -C ~/Documents all")[1] == ("files.documents:write",)
    assert classify_shell("cat a")[1] == ()  # without a move, `a` is under home, not Documents
    assert classify_shell("cd ~/Documents && cd .. && cat a")[1] == ("files.documents:read",)
    assert classify_shell("env -C ~/Documents rm a")[1] == ("files.documents:write",)
