"""Table-driven tests for flag-spelling coverage in classify_shell (F2, R99)."""

from pathlib import Path

import pytest

from jarvis.policy.model import Tier
from jarvis.policy.shell import classify_shell


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/jarvis-test")
    monkeypatch.setenv("USERPROFILE", "/home/jarvis-test")
    monkeypatch.chdir(tmp_path)


T3_INLINE_PROGRAMS = [
    "python3 -c 'x'",
    "python3 -cprint(1)",
    "python3 -Ic 'x'",
    "python3 -Bc 'x'",
    "python -c x",
    "python3.12 -c x",
    "perl -e 1",
    "perl -E 1",
    "perl -eprint",
    "perl -pe 1",
    "perl -ne 1",
    "perl -Ee 1",
    "ruby -e 1",
    "ruby -eputs",
    "node -e 1",
    "node -p 1",
    "node --eval 1",
    "node --eval=1",
    "node --print 1",
    "node --print=1",
    "node -pe 1",
    "php -r 1",
    "php -rprint(1);",
    "lua -e 1",
    "lua -eprint(1)",
    "osascript -e beep",
    "osascript -ebeep",
    "pwsh -c ls",
    "pwsh -Command ls",
    "pwsh -command ls",
    "pwsh -Comm ls",
    "pwsh -c:ls",
    "pwsh -EncodedCommand AAAA",
    "pwsh -ec AAAA",
    "powershell -Command ls",
    "powershell -c ls",
    "python3 - <<< 'print(1)'",
    "python3 <<< 'print(1)'",
    "perl <<< 'print 1'",
    "node <<< '1'",
    "python3 <<EOF\nprint(1)\nEOF",
]


@pytest.mark.parametrize("cmd", T3_INLINE_PROGRAMS, ids=T3_INLINE_PROGRAMS)
def test_should_classify_t3_for_every_spelling_of_an_inline_program(cmd: str) -> None:
    assert classify_shell(cmd)[0] == Tier.T3


T3_WRITE_TARGETS = [
    "cp --target-directory ~/.ssh x",
    "cp --target-directory=~/.ssh x",
    "cp -t ~/.ssh x",
    "cp -t~/.ssh x",
    "cp -at ~/.ssh x",
    "mv -t ~/.gnupg x",
    "mv --target-directory=/etc x",
    "install -Dt ~/.ssh k",
    "install -t ~/.ssh k",
    "install -m 600 k ~/.ssh/authorized_keys",
    "ln -s evil ~/.bashrc",
    "ln -sf evil ~/.bashrc",
    "ln -t ~/.ssh evil",
    "ln --target-directory ~/.ssh evil",
]


@pytest.mark.parametrize("cmd", T3_WRITE_TARGETS, ids=T3_WRITE_TARGETS)
def test_should_classify_t3_for_every_spelling_of_a_write_to_a_sensitive_target(cmd: str) -> None:
    assert classify_shell(cmd)[0] == Tier.T3


T3_R99_COMMANDS = [
    "rsync --del a b",
    "rsync --delete a b",
    "rsync --delete-after a b",
    "rsync -a --del a b",
    "sed -i s/a/b/ ~/.bashrc",
    "sed -i.bak s/a/b/ ~/.bashrc",
    "sed -ni p ~/.bashrc",
    "sed -Ei s/a/b/ ~/.zshrc",
    "sed --in-place s/a/b/ ~/.ssh/config",
    "sed --in-place=.bak s/a/b/ ~/.ssh/config",
    "crontab f",
    "crontab -",
    "crontab -u bob f",
    "systemctl --user enable x",
    "systemctl --user link x",
    "systemctl --user edit x",
    "systemctl enable x",
    "awk 'BEGIN{system(\"id\")}'",
    "awk '{print | \"sh\"}' f",
    "awk '{print > \"x\"}' f",
    "gawk 'BEGIN{system(\"id\")}'",
    "mawk '{print > \"x\"}' f",
    "awk -e 'BEGIN{system(\"id\")}'",
    "awk --source 'BEGIN{system(\"id\")}'",
]


@pytest.mark.parametrize("cmd", T3_R99_COMMANDS, ids=T3_R99_COMMANDS)
def test_should_classify_t3_for_the_r99_commands_and_rsync_abbreviations(cmd: str) -> None:
    assert classify_shell(cmd)[0] == Tier.T3


NEAR_MISSES = [
    "python3 --version",
    "python3 script.py",
    "python3 -m http.server",
    "python3 -mcompileall x",
    "python3 -",
    "node app.js",
    "perl script.pl",
    "pwsh -File x.ps1",
    "pwsh script.ps1",
    "cp a ~/Documents/b",
    "cp -t ~/Documents a b",
    "ln -s a b",
    "rsync -av a b",
    "rsync --dry-run a b",
    "sed -n p ~/.bashrc",
    "sed -i s/a/b/ notes.txt",
    "sed s/a/b/ ~/.bashrc",
    "crontab -l",
    "crontab -u bob -l",
    "systemctl status x",
    "systemctl restart x",
    "awk '{print $1}' f",
    "awk -F'|' '{print $1}' f",
    "awk -v x=1 '{print x}' f",
    "cat ~/.bashrc",
]


@pytest.mark.parametrize("cmd", NEAR_MISSES, ids=NEAR_MISSES)
def test_should_stay_below_t3_for_the_near_misses(cmd: str) -> None:
    assert classify_shell(cmd)[0] != Tier.T3
