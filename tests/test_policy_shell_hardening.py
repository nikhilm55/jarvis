"""Evasions of the shell classifier found in review: each must land on its FRS tier."""

import itertools
import re

import pytest

from jarvis.policy.model import Tier
from jarvis.policy.shell import classify_shell


def tier(cmd: str) -> Tier:
    return classify_shell(cmd)[0]


@pytest.mark.parametrize(
    "cmd",
    [
        "cat <(rm -rf ~)",
        "echo >(rm -rf ~)",
        "ls | tee >(sudo tee /etc/x)",
        "wc -l <(echo; sudo id)",
        "ionice sudo id",
        "chroot /mnt sudo id",
        "flock /tmp/l sudo id",
        "watch -n1 sudo id",
        "stdbuf -oL rm -rf ~",
        "busybox rm -rf ~",
        "timeout 5 sudo id",
        "taskset 1 shutdown now",
    ],
)
def test_should_classify_t3_when_a_dangerous_command_hides_in_a_substitution_or_wrapper(
    cmd: str,
) -> None:
    assert tier(cmd) == Tier.T3


@pytest.mark.parametrize(
    "cmd",
    [
        "ls >| ~/notes.txt",
        "ls >|f",
        "git log --outp=f",
        "git diff --outpu=f",
        "git log --output=f",
        "git diff --output-indicator-new=x",
        "git log --ext-diff",
        "git show --textconv HEAD",
        "git diff --no-index a b",
        "git status --ignore-submodules=x -c",
        "date --se=10:00",
        "date -us 10:00",
        "date -s 10:00",
        "date --set 10:00",
        "date -u",
        "date +%s +%F",
        "cat <(ls)",
        "echo >(cat)",
        "cat <<< hi",
        "cat << EOF",
        "ls |& wc",
        "ls |& tee f",
        "echo $(date)",
        "ls $(pwd)",
        "echo $HOME",
        "echo ${HOME}",
        "echo `date`",
        "(ls)",
        "ls &",
        "ls && ls",
        "ls || ls",
    ],
)
def test_should_classify_t2_when_a_read_command_can_write_expand_or_chain(cmd: str) -> None:
    assert tier(cmd) == Tier.T2


@pytest.mark.parametrize(
    "cmd",
    [
        "git log --oneline",
        "git log --oneline -n 5",
        "git log -5 --graph --decorate --all",
        "git log --format=%h -5",
        "git diff --stat",
        "git diff --cached --name-only",
        "git show HEAD",
        "git status -s",
        "git status --porcelain -b",
        "git branch -a",
        "date",
        "date +%s",
        "date +%F",
        "ls | wc -l",
        "wc -l < notes",
    ],
)
def test_should_keep_t0_when_the_command_is_a_plain_read(cmd: str) -> None:
    assert tier(cmd) == Tier.T0


_BASES = ["ls", "cat f", "echo hi", "date", "git status", "wc -l f", "pwd", "ps aux"]
_METAS = [
    " $(id)",
    " `id`",
    " > f",
    " >| f",
    " >> f",
    " <(id)",
    " >(id)",
    " &",
    " && id",
    " ; id",
    " $X",
    " ${X}",
    " (id)",
    " |& id",
    " || id",
    " <<< x",
    " << EOF",
    " | tee f",
    " | sh",
    " | python3",
    " | id",
    " 2>&1",
    " &> f",
    "\nid",
]
_PLAIN = re.compile(r"[\w .+/=,:@%-]+(?: \| [\w .+/=,:@%-]+)*(?: < [\w./-]+)?")


def test_should_never_classify_t0_when_a_command_holds_a_shell_metacharacter() -> None:
    """Ratchet: T0 only for a plain read, optionally piped to other reads or fed by `< file`."""
    corpus = [b + m for b, m in itertools.product(_BASES, _METAS)]
    corpus += [m.strip() + " " + b for b, m in itertools.product(_BASES, _METAS)]
    corpus += [b + m + m for b, m in itertools.product(_BASES, _METAS[:12])]
    for cmd in corpus:
        if tier(cmd) == Tier.T0:
            assert _PLAIN.fullmatch(cmd), cmd
    assert sum(tier(cmd) != Tier.T0 for cmd in corpus) > 400
