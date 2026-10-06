"""The PR-size gate counts reviewable lines only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_pr_size", ROOT / "scripts" / "check_pr_size.py"
)
assert spec and spec.loader
check_pr_size = importlib.util.module_from_spec(spec)
sys.modules["check_pr_size"] = check_pr_size
spec.loader.exec_module(check_pr_size)


def test_should_count_added_and_deleted_lines_when_files_are_code() -> None:
    total, skipped = check_pr_size.changed_lines(
        "10\t5\tsrc/jarvis/cli.py\n3\t0\ttests/test_cli.py"
    )
    assert total == 18
    assert skipped == []


def test_should_exclude_docs_lockfile_and_markdown_when_counting() -> None:
    numstat = "900\t0\tdocs/FRS.md\n400\t20\tuv.lock\n50\t0\tAGENTS.md\n7\t1\tsrc/jarvis/cli.py"
    total, skipped = check_pr_size.changed_lines(numstat)
    assert total == 8
    assert skipped == ["docs/FRS.md", "uv.lock", "AGENTS.md"]


def test_should_count_zero_when_file_is_binary() -> None:
    total, _ = check_pr_size.changed_lines("-\t-\tassets/icon.png")
    assert total == 0
