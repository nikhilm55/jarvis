"""N1: classifying a command line is bounded in length and work, whatever its shape.

`decide` runs in a worker thread that cannot be cancelled, so a line that made the classifier
run for seconds would hold a thread for good. These are the budget sensors (ratchet).
"""

import os
import time

import pytest

from jarvis.config import DEFAULT_CONSENT_FOLDERS
from jarvis.policy.model import Tier
from jarvis.policy.shell import (
    MAX_COMMAND_LENGTH,
    TOO_COMPLEX_REASON,
    TOO_LONG_REASON,
    classify_shell,
    shell_limit_reason,
)

_FOLDER_SOURCES = DEFAULT_CONSENT_FOLDERS.values()
LIMIT_S = 0.25 if os.environ.get("CI") else 0.05  # a generous factor for shared CI runners


def corpus() -> dict[str, str]:
    """Inputs of at most 4 KB that stress each way the classifier could blow up."""
    return {
        "eval chain": "eval " * 800 + "ls",
        "eval chain with rm": "eval " * 700 + "rm -rf ~",
        "sh -c chain": "sh -c " * 600 + "ls",
        "deep $(": "$(" * 1300 + "ls" + ")" * 1300,
        "deep backticks": "echo " + "`echo " * 300 + "ls" + "`" * 300,
        "deep <(": "cat " + "<(cat " * 500 + "ls" + ")" * 500,
        "many tokens": "ls " + "a " * 2040,
        "many distinct tokens": "ls " + " ".join(f"d{i}/f" for i in range(600)),
        "many commands": "ls;" * 1300,
        "many pipes": "ls |" * 1000 + " wc",
        "rm -f repeated": "rm -f " * 680,
        "wrappers": "nice " * 800 + "ls",
        "nested quotes": "echo " + "'\"'" * 1300,
        "one long token": "ls " + "a" * 4000,
        "heredocs": "cat <<EOF\n" + "x\n" * 1500 + "EOF",
        "here-strings": "bash " + "<<< x " * 600,
        "find exec": "find . " + "-exec rm {} ; " * 280,
        "assignments": "A=1 " * 1000 + "ls",
        "chroot paths": "chroot " + "/a " * 1300 + "su",
    }


@pytest.mark.parametrize("name", list(corpus()))
def test_should_classify_any_input_up_to_the_cap_within_the_time_limit(name: str) -> None:
    cmd = corpus()[name]
    assert len(cmd) <= MAX_COMMAND_LENGTH
    best = float("inf")
    for _ in range(3):  # the best of three, so a busy machine does not fail a correct run
        start = time.perf_counter()
        classify_shell(cmd)
        best = min(best, time.perf_counter() - start)
    assert best < LIMIT_S, f"{name}: {best * 1000:.1f} ms"


def test_should_classify_t3_with_a_reason_when_the_line_is_over_the_cap() -> None:
    cmd = "ls " + "a" * MAX_COMMAND_LENGTH
    assert len(cmd) > MAX_COMMAND_LENGTH
    assert classify_shell(cmd) == (Tier.T3, ())
    assert shell_limit_reason(cmd) == TOO_LONG_REASON == "too long to check"
    start = time.perf_counter()
    classify_shell("ls " + "a " * 100_000)  # a line far over the cap is refused unread
    assert time.perf_counter() - start < LIMIT_S


def test_should_not_refuse_a_line_exactly_at_the_cap() -> None:
    cmd = "echo " + "a" * (MAX_COMMAND_LENGTH - 5)
    assert len(cmd) == MAX_COMMAND_LENGTH
    assert classify_shell(cmd)[0] == Tier.T0
    assert shell_limit_reason(cmd) == ""


def test_should_classify_t3_with_a_reason_when_the_work_budget_runs_out() -> None:
    cmd = "eval " * 800 + "ls"
    assert classify_shell(cmd)[0] == Tier.T3
    assert shell_limit_reason(cmd) == TOO_COMPLEX_REASON == "too complex to check"


def test_should_still_read_a_nested_command_within_the_budget() -> None:
    assert classify_shell("eval " * 20 + "rm -rf ~")[0] == Tier.T3
    assert classify_shell("eval " * 20 + "ls")[0] == Tier.T2
    assert classify_shell("sh -c 'sh -c \"sh -c ls\"'")[0] == Tier.T2
    assert shell_limit_reason("eval " * 20 + "ls") == ""


def test_should_keep_the_budget_per_call_and_not_leak_it_between_calls() -> None:
    for _ in range(5):
        assert classify_shell("eval " * 800 + "ls")[0] == Tier.T3
        assert classify_shell("ls")[0] == Tier.T0


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("cat ~/notes/su", Tier.T0),
        ("ls ./format", Tier.T0),
        ("ls /usr/bin/su", Tier.T0),
        ("echo ~/halt", Tier.T0),
        ("cat notes/shutdown.txt", Tier.T0),
        ("su", Tier.T3),
        ("/usr/bin/sudo id", Tier.T3),
        ("./su", Tier.T3),
        ("env /usr/bin/sudo id", Tier.T3),
        ("chroot / /usr/bin/su", Tier.T3),
        ("nice -n 5 /sbin/shutdown now", Tier.T3),
        ("timeout 5 ~/bin/reboot", Tier.T3),
        ("echo su", Tier.T3),  # a bare word is still read as a possible command name
    ],
)
def test_should_read_a_path_as_a_path_and_a_bare_word_as_a_possible_command(
    cmd: str, expected: Tier
) -> None:
    assert classify_shell(cmd)[0] == expected


def test_should_assume_every_consent_folder_when_there_are_too_many_words_to_resolve() -> None:
    few = classify_shell("cat a b c")[1]
    assert few == ()
    many = classify_shell("cat " + "a " * 200)[1]
    assert many == tuple(sorted(f"{s}:{m}" for s in _FOLDER_SOURCES for m in ("read", "write")))
