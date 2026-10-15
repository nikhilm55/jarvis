"""The loop's deterministic sensors: pure functions, inline strings, no model, no git."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("harness_checks", ROOT / "scripts/harness_checks.py")
assert spec and spec.loader
hc = importlib.util.module_from_spec(spec)
sys.modules["harness_checks"] = hc
spec.loader.exec_module(hc)

SUITE = """import pytest

def test_a():
    assert 1
    with pytest.raises(ValueError):
        raise ValueError
    assert 2

async def test_b():
    assert 3

def helper():
    assert 4
"""


def stats(tests: int = 2, asserts: int = 4, raises: int = 1, skips: int = 0) -> object:
    return hc.TestStats(tests, asserts, raises, skips)


def test_should_count_tests_asserts_and_raises_when_reading_a_test_file() -> None:
    assert hc.test_stats(SUITE) == stats(tests=2, asserts=4, raises=1, skips=0)


@pytest.mark.parametrize(
    "marker",
    [
        "@pytest.mark.skip",
        "@pytest.mark.skip(reason='x')",
        "@pytest.mark.skipif(True, reason='x')",
        "@pytest.mark.xfail",
    ],
)
def test_should_count_one_skip_when_a_marker_is_added(marker: str) -> None:
    found = hc.test_stats(f"import pytest\n\n{marker}\ndef test_a():\n    assert 1\n")
    assert found is not None
    assert found.skips == 1


@pytest.mark.parametrize("call", ["pytest.skip('x')", "pytest.xfail('x')"])
def test_should_count_a_skip_when_the_test_calls_pytest_skip(call: str) -> None:
    found = hc.test_stats(f"import pytest\n\ndef test_a():\n    {call}\n")
    assert found is not None
    assert found.skips == 1


def test_should_return_none_when_the_test_file_does_not_parse() -> None:
    assert hc.test_stats("def test_a(:\n") is None


@pytest.mark.parametrize(
    ("after", "word"),
    [
        (stats(tests=1), "tests"),
        (stats(asserts=3), "asserts"),
        (stats(raises=0), "raises"),
        (stats(skips=1), "skips"),
    ],
)
def test_should_report_one_problem_when_a_test_file_gets_weaker(after: object, word: str) -> None:
    [problem] = hc.weakening(stats(), after)
    assert word in problem


def test_should_report_nothing_when_a_test_file_grows_or_stays_the_same() -> None:
    assert hc.weakening(stats(), stats()) == []
    assert hc.weakening(stats(), stats(tests=5, asserts=9, raises=3)) == []


def block(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"


def test_should_parse_every_block_and_ignore_the_text_around_them() -> None:
    reply = "intro\n" + block("a\nb\n", "c\n") + "between\n" + block("x\n", "") + "bye"
    assert hc.parse_edits(reply) == [hc.Edit("a\nb\n", "c\n"), hc.Edit("x\n", "")]


def test_should_ignore_an_unterminated_block() -> None:
    assert hc.parse_edits("<<<<<<< SEARCH\na\n=======\nb\n") == []
    assert hc.parse_edits("<<<<<<< SEARCH\na\n") == []


def test_should_apply_edits_in_order_on_the_running_content() -> None:
    edits = [hc.Edit("A = 1\n", "A = 2\n"), hc.Edit("A = 2\n", "A = 3\n")]
    assert hc.apply_edits("A = 1\nB = 1\n", edits) == ("A = 3\nB = 1\n", [])


@pytest.mark.parametrize(
    ("search", "error"),
    [("zzz\n", "edit 1: SEARCH not found"), ("x = 1\n", "edit 1: SEARCH matches 2 times")],
)
def test_should_reject_a_block_that_does_not_match_exactly_once(search: str, error: str) -> None:
    content = "x = 1\nx = 1\ny = 2\n"
    assert hc.apply_edits(content, [hc.Edit(search, "q\n")]) == (content, [error])


def test_should_reject_an_empty_search_and_keep_applying_the_other_blocks() -> None:
    edits = [hc.Edit("", "q\n"), hc.Edit("a\n", "b\n")]
    assert hc.apply_edits("a\n", edits) == ("b\n", ["edit 1: SEARCH is empty"])


REPORT = """RUFF:
src/a.py:3:1: F401 `os` imported but unused
src/b.py:9:5: E501 Line too long

MYPY:
src/a.py:7: error: Incompatible return value type  [return-value]
src/c.py:2: error: Missing attr  [attr-defined]

PYTEST:
..F
FAILED tests/test_a.py::test_x - assert 0
FAILED tests/test_a.py::test_y
ERROR tests/test_b.py - ImportError: nope
"""


def test_should_fingerprint_test_ids_and_lint_codes_with_file_and_line() -> None:
    assert hc.fingerprint(REPORT).splitlines() == [
        "mypy src/a.py:7 return-value",
        "mypy src/c.py:2 attr-defined",
        "ruff src/a.py:3 F401",
        "ruff src/b.py:9 E501",
        "tests/test_a.py::test_x",
        "tests/test_a.py::test_y",
        "tests/test_b.py",
    ]


def test_should_fingerprint_the_same_when_only_the_messages_change() -> None:
    reworded = REPORT.replace("assert 0", "assert 1").replace("Missing attr", "No attr")
    assert hc.fingerprint(reworded) == hc.fingerprint(REPORT)


def test_should_fingerprint_unparsed_reports_without_digits_and_blank_as_empty() -> None:
    assert hc.fingerprint("boom at   line 12\n") == hc.fingerprint("boom at line 99")
    assert hc.fingerprint(" \n") == ""


def test_should_split_a_report_into_sections_keeping_blank_lines_inside_pytest() -> None:
    parts = hc.split_report(REPORT + "\n\n    trace\n")
    assert list(parts) == ["RUFF", "MYPY", "PYTEST"]
    assert parts["MYPY"].count("\n") == 1
    assert parts["PYTEST"].endswith("trace")


def test_should_route_only_the_lines_that_mention_the_file_plus_the_pytest_summaries() -> None:
    routed = hc.errors_for_file(REPORT, "src/a.py")
    assert routed["RUFF"] == "src/a.py:3:1: F401 `os` imported but unused"
    assert routed["MYPY"] == "src/a.py:7: error: Incompatible return value type  [return-value]"
    assert routed["PYTEST"].splitlines()[0].startswith("FAILED tests/test_a.py::test_x")
    assert set(hc.errors_for_file(REPORT, "src/b.py")) == {"RUFF", "PYTEST"}
    assert "src/b.py" not in routed["RUFF"]


def test_should_route_nothing_when_no_line_mentions_the_file_and_nothing_failed() -> None:
    assert hc.errors_for_file("RUFF:\nsrc/b.py:1:1: E1 x", "src/a.py") == {}


def test_should_find_test_files_that_fail_to_collect_but_not_failing_tests() -> None:
    report = (
        "___ ERROR collecting tests/test_b.py ___\nImportError\n"
        "ERROR tests/test_b.py - ImportError: nope\nERROR tests/test_c.py::test_z - boom\n"
        "FAILED tests/test_d.py::test_q\n"
    )
    assert hc.collection_errors(report) == {"tests/test_b.py"}


def test_should_read_paths_from_porcelain_output() -> None:
    out = ' M src/a.py\n?? "dir/sp ace.py"\nR  old.py -> new.py\n\nA  b.py\n'
    assert hc.porcelain_paths(out) == {"src/a.py", "dir/sp ace.py", "old.py", "new.py", "b.py"}


def test_should_flag_only_paths_outside_the_scope() -> None:
    out = " M src/a.py\n M other.py\n?? stray.txt\n?? .runs/x/log.md\n M was_dirty.py\n"
    found = hc.scope_violations(out, {"src/a.py"}, {"was_dirty.py"}, (".runs/",))
    assert found == ["other.py", "stray.txt"]
    assert hc.scope_violations(" M src/a.py\n", {"src/a.py"}, set()) == []
