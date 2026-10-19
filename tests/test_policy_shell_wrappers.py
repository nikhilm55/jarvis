"""Wrapper corpus: a destructive payload run through every wrapper must stay T3 (R94, F1)."""

import pytest

from jarvis.policy.model import Tier
from jarvis.policy.shell import classify_shell

_WRAPPER_PREFIXES: dict[str, list[str]] = {
    "timeout": ["5s"],
    "taskset": ["0x1", "-c 0,1"],
    "nice": ["-n 5"],
    "ionice": ["-c 3 -n 7"],
    "runuser": ["-u bob --"],
    "chrt": ["10"],
    "stdbuf": ["-oL", "-o L"],
    "setpriv": ["--reuid 1000"],
    "unshare": ["-m"],
    "env": ["-i FOO=1"],
    "flock": ["/run/lock/l"],
    "chroot": ["/"],
    "watch": ["-n 1"],
    "nsenter": ["-t 1"],
    "xargs": ["-n 1"],
    "nohup": [""],
    "time": [""],
    "command": [""],
    "exec": [""],
    "setsid": [""],
    "unbuffer": [""],
    "busybox": [""],
}

_PAYLOADS = [
    "rm -rf ~",
    "/bin/rm -rf ~",
    "bash -c 'rm -rf ~'",
    "/bin/bash -c 'rm -rf ~'",
    "eval 'rm -rf ~'",
]

_DATA_COMMANDS = [
    "cat ~/notes/su",
    "ls ./format",
    "ls /usr/bin/su",
    "echo ~/halt",
    "cat notes/shutdown.txt",
]

_HARMLESS_PAYLOADS = ["ls", "/bin/ls"]


def _wrapper_forms() -> list[tuple[str, str]]:
    forms: list[tuple[str, str]] = []
    for name, prefixes in _WRAPPER_PREFIXES.items():
        for prefix in prefixes:
            forms.append((name, prefix))
    return forms


def _destructive_cases() -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    for name, prefix in _wrapper_forms():
        for form in (name, f"/usr/bin/{name}"):
            for payload in _PAYLOADS:
                cases.append((form, prefix, payload))
    return cases


def _harmless_cases() -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    for name, prefix in _wrapper_forms():
        for form in (name, f"/usr/bin/{name}"):
            for payload in _HARMLESS_PAYLOADS:
                cases.append((form, prefix, payload))
    return cases


DESTRUCTIVE_CASES = _destructive_cases()
HARMLESS_CASES = _harmless_cases()


@pytest.mark.parametrize(
    ("form", "prefix", "payload"),
    DESTRUCTIVE_CASES,
    ids=[
        f"{form}-{prefix or 'no-prefix'}-{payload}" for form, prefix, payload in DESTRUCTIVE_CASES
    ],
)
def test_should_classify_t3_when_a_wrapper_runs_a_destructive_payload(
    form: str, prefix: str, payload: str
) -> None:
    cmd = f"{form} {prefix} {payload}".strip()
    tier = classify_shell(cmd)[0]
    assert tier == Tier.T3, f"expected T3 for {cmd!r}, got {tier}"


@pytest.mark.parametrize(
    "cmd",
    _DATA_COMMANDS,
    ids=[f"data-{cmd}" for cmd in _DATA_COMMANDS],
)
def test_should_stay_below_t3_when_a_path_is_only_data(cmd: str) -> None:
    tier = classify_shell(cmd)[0]
    assert tier != Tier.T3, f"expected below T3 for {cmd!r}, got {tier}"


@pytest.mark.parametrize(
    ("form", "prefix", "payload"),
    HARMLESS_CASES,
    ids=[f"{form}-{prefix or 'no-prefix'}-{payload}" for form, prefix, payload in HARMLESS_CASES],
)
def test_should_stay_below_t3_when_the_wrapper_runs_a_harmless_command(
    form: str, prefix: str, payload: str
) -> None:
    cmd = f"{form} {prefix} {payload}".strip()
    tier = classify_shell(cmd)[0]
    assert tier != Tier.T3, f"expected below T3 for {cmd!r}, got {tier}"
