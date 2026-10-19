"""The test lock against ruff: the same revert twice is a lock/lint conflict, not weakening."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from .test_local_model import FakeChecks, FakeModel, fenced, implement, local_model

# The rig's fixtures under aliases (see test_local_model_loopbugs.py).
from .test_local_model import clean_git_env as _clean_git_env  # noqa: F401
from .test_local_model import repo as rig_repo  # noqa: F401

DRAFT = "from rig import repo\n\n\ndef test_a(repo) -> None:\n    assert 1\n    assert 2\n"
IMPORT = "from rig import repo\n\n\n"
MYPY = "MYPY:\nsrc/new.py:1: error: boom  [misc]"


@pytest.fixture
def repo(request: pytest.FixtureRequest) -> Path:
    path: Path = request.getfixturevalue("rig_repo")
    return path


def ruff_strips_the_import(repo: Path, rel: str) -> str:
    """Stands in for `ruff_result`: what ruff makes of the file in `repo`."""
    return (repo / rel).read_text(encoding="utf-8").replace(IMPORT, "")


def strip_fixture_import(repo: Path) -> None:
    """What `ruff --fix` does to an import it thinks is unused."""
    test = repo / "tests" / "test_new.py"
    if test.exists():
        test.write_text(test.read_text(encoding="utf-8").replace(IMPORT, ""), encoding="utf-8")


def test_should_call_the_same_revert_twice_a_lint_lock_conflict(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_model, "fixable_rules", lambda repo, rel: ["F401"])
    monkeypatch.setattr(local_model, "ruff_result", ruff_strips_the_import)
    model = FakeModel({"tests/test_new.py": fenced(DRAFT)})
    checks = FakeChecks((False, MYPY), effect=strip_fixture_import)
    code, summary, _ = implement(repo, monkeypatch, model, checks, rounds=4)
    assert (summary["status"], code, summary["rounds"]) == ("lint_lock_conflict", 1, 1)
    [conflict] = summary["lint_conflicts"]
    assert (conflict["file"], conflict["round"], conflict["rules"]) == (
        "tests/test_new.py",
        1,
        ["F401"],
    )
    assert {e["source"] for e in summary["weakening_events"]} == {"lint"}
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == DRAFT  # the lock held


def test_should_keep_test_weakened_when_ruff_changed_the_file_only_once(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_model, "ruff_result", ruff_strips_the_import)
    once = [strip_fixture_import]

    def effect(repo: Path) -> None:
        if once:
            once.pop()(repo)

    model = FakeModel({"tests/test_new.py": fenced(DRAFT)})
    checks = FakeChecks((False, MYPY), (True, ""), effect=effect)
    _, summary, _ = implement(repo, monkeypatch, model, checks)
    assert summary["status"] == "test_weakened"
    assert summary["lint_conflicts"] == []


def test_should_name_the_ruff_rules_that_would_fix_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = [
        {"code": "F401", "fix": {"applicability": "safe"}},
        {"code": "E501", "fix": None},
        {"code": "I001", "fix": {"applicability": "safe"}},
        {"code": "F401", "fix": {"applicability": "safe"}},
    ]
    answers = [json.dumps(found), json.dumps([{"code": "E501", "fix": None}]), "not json"]
    monkeypatch.setattr(local_model, "run_split", lambda cmd, repo: (1, answers.pop(0), ""))
    assert local_model.fixable_rules(tmp_path, "tests/x.py") == ["F401", "I001"]
    assert local_model.fixable_rules(tmp_path, "tests/x.py") == ["format"]  # the formatter's change
    assert local_model.fixable_rules(tmp_path, "tests/x.py") == ["format"]


def rewrite_the_test(repo: Path) -> None:
    """Code under test that edits the locked test while pytest runs (ruff has nothing to do)."""
    test = repo / "tests" / "test_new.py"
    test.write_text(test.read_text(encoding="utf-8").replace("assert 2", "assert True"), "utf-8")


def test_should_call_a_runtime_rewrite_of_the_locked_test_a_weakened_test(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        local_model, "ruff_result", lambda repo, rel: (repo / rel).read_text("utf-8")
    )
    monkeypatch.setattr(local_model, "fixable_rules", lambda repo, rel: ["format"])
    model = FakeModel({"tests/test_new.py": fenced(DRAFT)})
    checks = FakeChecks((False, MYPY), effect=rewrite_the_test)
    code, summary, _ = implement(repo, monkeypatch, model, checks, rounds=3)
    assert (summary["status"], code) == ("test_weakened", 1)
    assert summary["lint_conflicts"] == []
    assert {e["source"] for e in summary["weakening_events"]} == {"check"}
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == DRAFT  # the lock held


@pytest.mark.skipif(sys.platform != "linux", reason="stubs `uv` with a sh script")
def test_should_ask_real_ruff_what_it_makes_of_the_locked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"  # `uv run --quiet ruff ...` -> `python -m ruff ...`
    uv.write_text(f'#!/bin/sh\nshift 2\nexec {sys.executable} -m "$@"\n', encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    (tmp_path / "t.py").write_text("import os\nx  =  1\n", encoding="utf-8")
    assert (
        local_model.ruff_result(tmp_path, "t.py") == "\nx = 1\n"
    )  # formatted, then the unused import dropped
