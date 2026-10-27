"""R94: permanent deletion and privilege changes are T3, whatever the command is dressed as."""

import pytest

from jarvis.policy.model import Tier
from jarvis.policy.shell import classify_shell


def tier(cmd: str) -> Tier:
    return classify_shell(cmd)[0]


@pytest.mark.parametrize(
    "cmd",
    [
        "su",
        "su -c 'id'",
        "su - root",
        "env su root",
        "find / -delete",
        "find ~ -name '*.tmp' -delete",
        "find ~ -exec rm {} +",
        "find . -execdir rm -f {} ;",
        "find . -exec shred {} ;",
        "git clean -fdx",
        "git clean -f -d",
        "git clean -ffx",
        "git clean --force -d",
        "git -C repo clean -fdX",
        "python3 -c 'import shutil; shutil.rmtree(\"/x\")'",
        "python -c \"import os; os.remove('f')\"",
        "python3.12 -c 'import pathlib; pathlib.Path(\"f\").unlink()'",
        "perl -e 'unlink glob \"*\"'",
        "perl -ne 'unlink'",
        'ruby -e \'FileUtils.rm_rf("x"); File.unlink("y")\'',
        'node -e \'require("fs").rmSync("x", {recursive: true})\'',
        'node -p \'require("fs").unlinkSync("x")\'',
        "python3 -c 'import os; os.system(\"rm -rf ~\")'",
        "python3 -c",
        "mv ~ /tmp",
        "mv $HOME /tmp/h",
        "mv ${HOME} /tmp/h",
        "mv / /tmp/r",
        "mv /etc /tmp/etc",
        "mv /usr/ /tmp/usr",
        "mv . /tmp/h",
        "mv a ~",
        "mv $X /tmp",
        "chmod 000 ~",
        "chmod 755 /",
        "chmod 777 /",
        "chown me ~",
        "chown -R me:me $HOME",
        "crontab -r",
        "shred -u secret",
        "wipefs -a /dev/sdb",
        "kill -9 1",
        "kill 1",
        "kill -9 -1",
        "pkill -9 -1",
        "killall -1",
        "systemctl stop sshd",
        "systemctl disable --now sshd",
        "systemctl --user mask x",
        "ufw disable",
        "setenforce 0",
        "setenforce Permissive",
        "iptables -F",
        "iptables --flush",
        "ip6tables -t nat -F",
        "nft flush ruleset",
    ],
)
def test_should_classify_t3_when_a_command_deletes_for_good_or_weakens_the_system(
    cmd: str,
) -> None:
    assert tier(cmd) == Tier.T3


@pytest.mark.parametrize(
    "cmd",
    [
        "find . -name '*.py'",
        "find ~ -type f -exec ls {} ;",
        "find . -exec grep x {} ;",
        "git clean -n",
        "git clean -fn",
        "git clean -f",
        "git reset --hard",
        "git push --force",
        "git checkout main",
        "python3 -c 'print(1)'",
        "python3 script.py",
        "perl -e 'print 1'",
        "node -e 'console.log(1)'",
        "mv a b",
        "mv Documents/a Documents/b",
        "mv -t /tmp a b",
        "chmod 600 notes.txt",
        "chmod -R u+rwX Documents",
        "chown me file",
        "crontab -l",
        "kill 1234",
        "kill -9 4321",
        "pkill firefox",
        "systemctl status sshd",
        "systemctl restart sshd",
        "systemctl --user start x",
        "ufw status",
        "setenforce 1",
        "iptables -L",
        "nft list ruleset",
    ],
)
def test_should_keep_t2_when_the_command_only_looks_like_a_destructive_one(cmd: str) -> None:
    assert tier(cmd) == Tier.T2
