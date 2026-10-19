"""The test lock against ruff: the same revert twice is a lock/lint conflict, not weakening."""

from __future__ import annotations

import json
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


def strip_fixture_import(repo: Path) -> None:
    """What `ruff --fix` does to an import it thinks is unused."""
    test = repo / "tests" / "test_new.py"
    if test.exists():
        test.write_text(test.read_text(encoding="utf-8").replace(IMPORT, ""), encoding="utf-8")


def test_should_call_the_same_revert_twice_a_lint_lock_conflict(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_model, "fixable_rules", lambda repo, rel: ["F401"])
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
