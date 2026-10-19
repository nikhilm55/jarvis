"""Deny-list inversion property tests (F3)."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from jarvis.config import PolicySettings
from jarvis.policy.lists import denied

DENY = PolicySettings(deny_paths=["~/work/secrets"])

NON_ALLOWLISTED_TEMPLATES = [
    "cat {p}",
    "cp -r {p} /tmp/out",
    "cp -s {p} /tmp/l",
    "ln -s {p} /tmp/l",
    "tar -czf /tmp/a.tgz {p}",
    "bsdtar -czf /tmp/a.tgz {p}",
    "rclone copy {p} remote:x",
    "fd . {p}",
    "find {p} -name k",
    "grep -r token {p}",
    "du -a {p}",
    "rsync -a {p} /tmp/o",
    "mount --bind {p} /mnt",
    "bindfs {p} /mnt",
    "echo {p}",
    "env cat {p}",
    "nice cat {p}",
    "ls -R {p}",
    "ls --recursive {p}",
    "zip -r /tmp/a.zip {p}",
    "7z a /tmp/a.7z {p}",
    "chmod -R 777 {p}",
    "rm -r {p}",
    "mv {p} /tmp/w",
]

PATH_FORMS = ["~/work/secrets", "~/work", "~", ".", "/", "$HOME/work", "${HOME}/work"]

ALLOWLISTED_COMMANDS = [
    "ls {p}",
    "stat {p}",
    "file {p}",
    "test -d {p}",
    "[ -d {p} ]",
    "realpath {p}",
    "readlink {p}",
    "basename {p}",
    "dirname {p}",
]

PARENT_FORMS = ["~/work", "~", "/", "$HOME/work"]

CHOOSE_PIPE_TEMPLATES = ["cat {p}", "cp -r {p} /tmp/out", "fd . {p}"]


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "work" / "secrets").mkdir(parents=True)


@pytest.mark.parametrize(
    "non_allowlisted_template,path_form",
    list(itertools.product(NON_ALLOWLISTED_TEMPLATES, PATH_FORMS)),
)
def test_should_deny_a_non_allowlisted_command_for_a_protected_folder_or_a_parent(
    non_allowlisted_template: str, path_form: str
) -> None:
    line = non_allowlisted_template.format(p=path_form)
    assert denied({"cmd": line}, DENY) is not None

    wrapped = f"ln -s {path_form} /tmp/l && cat /tmp/l/secrets/k"
    assert denied({"cmd": wrapped}, DENY) is not None

    assert denied({"cmd": f"echo hi; {line}"}, DENY) is not None

    if non_allowlisted_template in CHOOSE_PIPE_TEMPLATES:
        assert denied({"cmd": f"true | {line}"}, DENY) is not None


@pytest.mark.parametrize(
    "allowlisted_command,parent_form",
    list(itertools.product(ALLOWLISTED_COMMANDS, PARENT_FORMS)),
)
def test_should_allow_a_read_only_command_for_a_parent_of_the_protected_folder(
    allowlisted_command: str, parent_form: str
) -> None:
    line = allowlisted_command.format(p=parent_form)
    assert denied({"cmd": line}, DENY) is None


@pytest.mark.parametrize("allowlisted_command", ALLOWLISTED_COMMANDS)
def test_should_deny_a_read_only_command_for_the_protected_folder_itself(
    allowlisted_command: str,
) -> None:
    line = allowlisted_command.format(p="~/work/secrets")
    assert denied({"cmd": line}, DENY) is not None


@pytest.mark.parametrize(
    "line",
    [t.format(p=p) for t, p in itertools.product(NON_ALLOWLISTED_TEMPLATES, PATH_FORMS)]
    + [c.format(p=p) for c, p in itertools.product(ALLOWLISTED_COMMANDS, PARENT_FORMS)],
)
def test_should_deny_nothing_when_no_deny_list_is_set(line: str) -> None:
    assert denied({"cmd": line}, PolicySettings()) is None


@pytest.mark.parametrize("template", ["cat {p}", "ln -s {p} /tmp/l", "fd . {p}"])
@pytest.mark.parametrize(
    "shape",
    [
        lambda line: {"cmd": line},
        lambda line: {"script": line},
        lambda line: {"note": line},
        lambda line: {"plan": [{"step": line}]},
    ],
    ids=["cmd", "script", "note", "nested"],
)
def test_should_deny_the_same_line_under_any_argument_key_and_depth(
    template: str, shape: Callable[[str], Mapping[str, object]]
) -> None:
    assert denied(shape(template.format(p="~/work")), DENY) is not None
