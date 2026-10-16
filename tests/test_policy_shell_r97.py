"""R97 (writes that give lasting control) and R98 (inline interpreter programs) are T3."""

from pathlib import Path

import pytest

from jarvis.policy.model import Tier
from jarvis.policy.shell import classify_shell


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A home that is not under /tmp (pytest's tmp_path is), so `dd of=b` is not a temp file."""
    monkeypatch.setenv("HOME", "/home/jarvis-test")
    monkeypatch.setenv("USERPROFILE", "/home/jarvis-test")
    monkeypatch.chdir(tmp_path)


def tier(cmd: str) -> Tier:
    return classify_shell(cmd)[0]


@pytest.mark.parametrize(
    "cmd",
    [
        "rsync -av --delete a/ b/",
        "rsync -a --delete-after a b",
        "rsync --delete-excluded a b",
        "dd if=a of=b",
        "dd if=/dev/zero of=~/disk.img",
        "dd of=/etc/x if=y",
        "dd if=a of=$X",
        "echo x > ~/.bashrc",
        "echo x >> ~/.profile",
        "echo x >| ~/.zshrc",
        "echo x &> ~/.bash_profile",
        "cat key >> ~/.ssh/authorized_keys",
        "echo x > ~/.config/fish/config.fish",
        "echo x > ~/.config/autostart/x.desktop",
        "echo x > ~/.config/systemd/user/x.service",
        "echo x > ~/.local/share/systemd/user/x.service",
        "echo x > /etc/hosts",
        "echo x > /var/spool/cron/me",
        "echo x > $HOME/.bashrc",
        "echo x | tee ~/.bashrc",
        "echo x | tee -a ~/.ssh/config",
        "echo x | tee /tmp/ok ~/.profile",
        "cp evil ~/.bashrc",
        "cp -r evil ~/.ssh",
        "cp -t ~/.gnupg a b",
        "cp --target-directory=/etc a",
        "mv evil ~/.zshrc",
        "mv -f a /etc/passwd",
        "install -m 600 k ~/.ssh/authorized_keys",
        "ln -s evil ~/.bashrc",
        "ln -sf /tmp/x ~/.config/autostart/x",
        "truncate -s 0 ~/.ssh/config",
        "truncate -s 0 /etc/fstab",
        "python3 -c 'print(1)'",
        "python -c 'x'",
        "python3 -Bc 'x'",
        "perl -e 'print 1'",
        "perl -E 'say 1'",
        "perl -pe 's/a/b/'",
        "ruby -e 'puts 1'",
        "node -e 'console.log(1)'",
        "node -p '1+1'",
        "node --eval '1'",
        "php -r 'echo 1;'",
        "lua -e 'print(1)'",
        "osascript -e 'beep'",
        "pwsh -c 'ls'",
        "pwsh -Command ls",
        "pwsh -command ls",
        "powershell -EncodedCommand AAAA",
        "nice -n 5 python3 -c 'x'",
    ],
)
def test_should_classify_t3_when_the_command_writes_a_sensitive_place_or_runs_inline_code(
    cmd: str,
) -> None:
    assert tier(cmd) == Tier.T3


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("rsync -av a b", Tier.T2),
        ("rsync --dry-run a b", Tier.T2),
        ("dd if=a of=/tmp/b", Tier.T2),
        ("dd if=/dev/zero bs=1 count=1", Tier.T2),
        ("cat ~/.bashrc", Tier.T0),
        ("ls ~/.ssh", Tier.T0),
        ("head -n 3 /etc/hosts", Tier.T0),
        ("cp ~/.bashrc /tmp/bashrc", Tier.T2),
        ("cp -r ~/.ssh /tmp/ssh-copy", Tier.T2),
        ("cp a ~/Documents/b", Tier.T2),
        ("mv ~/.zshrc ~/zshrc.old", Tier.T2),
        ("install -m 755 tool ~/bin/tool", Tier.T2),
        ("ln -s a b", Tier.T2),
        ("ln -s a ~/etc-notes", Tier.T2),
        ("echo x > ~/notes.txt", Tier.T2),
        ("echo x > ~/.bashrc.bak", Tier.T2),
        ("echo x | tee ~/out.txt", Tier.T2),
        ("echo x > /tmp/etc", Tier.T2),
        ("truncate -s 0 ~/log.txt", Tier.T2),
        ("python3 --version", Tier.T2),
        ("python3 script.py", Tier.T2),
        ("python3 -m http.server", Tier.T2),
        ("python3 -", Tier.T2),
        ("perl script.pl", Tier.T2),
        ("node app.js", Tier.T2),
        ("pwsh script.ps1", Tier.T2),
        ("osascript script.scpt", Tier.T2),
    ],
)
def test_should_keep_the_tier_when_the_command_only_resembles_a_t3_one(
    cmd: str, expected: Tier
) -> None:
    assert tier(cmd) == expected
