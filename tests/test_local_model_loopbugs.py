"""Tests for the three loop bugs: no-change detection, tool-call retry, pytest timeout."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from .test_local_model import (
    FAILED,
    IMPL_SRC,
    FakeChecks,
    FakeModel,
    fenced,
    implement,
    local_model,
)

# One copy of the module and the rig: `implement` patches the rig's `local_model`. The rig's
# fixtures come in under aliases so ruff's unused-import fix leaves them alone (F401 is waived).
from .test_local_model import clean_git_env as _clean_git_env  # noqa: F401
from .test_local_model import repo as rig_repo  # noqa: F401


@pytest.fixture
def repo(request: pytest.FixtureRequest) -> Path:
    path: Path = request.getfixturevalue("rig_repo")
    return path


def test_should_report_no_change_when_the_model_changed_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel(
        {"tests/test_new.py": "ok, nothing to change", "src/new.py": "ok, nothing to change"}
    )
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert summary["status"] == "no_change"
    assert code == 1
    assert summary["untouched"] == ["src/new.py", "tests/test_new.py"]


def test_should_report_green_and_no_untouched_files_on_a_normal_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel()
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert summary["status"] == "green"
    assert code == 0
    assert summary["untouched"] == []


def test_should_retry_once_when_the_first_reply_is_a_tool_call(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_call = '<tool_call>{"name": "x"}</tool_call>'
    model = FakeModel({"src/new.py": [tool_call, fenced(IMPL_SRC)]})
    implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert (repo / "src" / "new.py").read_text(encoding="utf-8") == IMPL_SRC
    prompts = model.prompts("src/new.py")
    assert len(prompts) == 2
    assert "Do not call tools" in prompts[1]
    assert "Do not call tools" not in prompts[0]


def test_should_note_when_both_replies_are_tool_calls(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_call = '<tool_call>{"name": "x"}</tool_call>'
    model = FakeModel({"src/new.py": [tool_call, tool_call]})
    checks = FakeChecks((False, FAILED + "\nsrc/new.py"), (True, ""))
    implement(repo, monkeypatch, model, checks)
    prompts = model.prompts("src/new.py")
    # round 0 and the fix round are two writes: each is one call plus exactly one retry
    assert len(prompts) == 4
    retried = ["Do not call tools" in p for p in prompts]
    assert retried == [False, True, False, True]
    assert "- reply was a tool call, not code" in prompts[2]


def test_should_not_retry_a_plain_prose_reply(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel({"src/new.py": "I cannot do that."})
    implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert len(model.prompts("src/new.py")) == 1


def test_should_treat_a_hanging_pytest_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_split(cmd: list[str], repo: Path) -> tuple[int, str, str]:
        if cmd[:3] == ["uv", "run", "--quiet"] and cmd[3] == "pytest":
            raise subprocess.TimeoutExpired(cmd, 300)
        return 0, "", ""

    monkeypatch.setattr(local_model, "run_split", fake_run_split)
    ok, report = local_model.check(tmp_path, [], ["tests"], tmp_path / "c", (0, 0))
    assert ok is False
    assert "TIMEOUT:" in report
    assert "PYTEST:" in report


def test_should_give_pytest_the_flag_timeout_and_the_other_tools_15_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, int] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen[cmd[3]] = kw["timeout"]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(local_model, "PYTEST_TIMEOUT_S", 7)
    monkeypatch.setattr(local_model.subprocess, "run", fake_run)
    local_model.check(tmp_path, ["a.py"], ["tests"], tmp_path / "c", (0, 0))
    assert seen == {"ruff": 900, "mypy": 900, "pytest": 7}


def test_should_set_the_pytest_timeout_from_the_flag(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_model, "PYTEST_TIMEOUT_S", 300)  # restored after the test
    seen: list[int] = []
    checks = FakeChecks((True, ""), effect=lambda _: seen.append(local_model.PYTEST_TIMEOUT_S))
    (repo.parent / "brief.md").write_text("brief", encoding="utf-8")
    argv = ["implement", "--repo", str(repo), "--spec", str(repo.parent / "brief.md")]
    argv += ["--write", "tests/test_new.py", "src/new.py", "--test", "tests"]
    argv += ["--log-dir", str(repo.parent / "log"), "--rounds", "1", "--test-timeout", "7"]
    monkeypatch.setattr(local_model, "chat", FakeModel())
    monkeypatch.setattr(local_model, "check", checks)
    local_model.main(argv)
    assert seen
    assert set(seen) == {7}
