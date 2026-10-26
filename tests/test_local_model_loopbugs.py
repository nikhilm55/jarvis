"""Tests for the three loop bugs: no-change detection, tool-call retry, pytest timeout."""

from __future__ import annotations

import os
import subprocess
import sys
import time
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

    class FakeProc:
        def __init__(self, cmd: list[str], **kw: Any) -> None:
            self.cmd, self.returncode = cmd, 0

        def __enter__(self) -> FakeProc:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def communicate(self, timeout: int) -> tuple[str, str]:
            seen[self.cmd[3]] = timeout
            return "", ""

    monkeypatch.setattr(local_model, "PYTEST_TIMEOUT_S", 7)
    monkeypatch.setattr(local_model.subprocess, "Popen", FakeProc)
    local_model.check(tmp_path, ["a.py"], ["tests"], tmp_path / "c", (0, 0))
    assert seen == {"ruff": 900, "mypy": 900, "pytest": 7}


def alive(pid: int) -> bool:
    """Is the process running (a zombie waiting to be reaped is dead)?"""
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.mark.skipif(
    sys.platform != "linux", reason="looks for survivors in /proc and stubs `uv` with a sh script"
)
def test_should_kill_the_hung_tests_whole_process_group_on_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    pids = tmp_path / "pids.txt"
    (repo / "tests" / "test_hang.py").write_text(
        "import subprocess, sys, time\n\n\ndef test_hang():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"    open({str(pids)!r}, 'w').write(str(child.pid))\n"
        "    time.sleep(600)\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"  # `uv run --quiet <tool> ...` -> `python -m <tool> ...`
    uv.write_text(f'#!/bin/sh\nshift 2\nexec {sys.executable} -m "$@"\n', encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(local_model, "PYTEST_TIMEOUT_S", 3)
    started = time.monotonic()
    ok, report = local_model.check(repo, [], ["tests"], tmp_path / "cache", (0, 0))
    assert time.monotonic() - started < 30
    assert ok is False
    assert "TIMEOUT:" in report
    grandchild = int(pids.read_text(encoding="utf-8"))
    time.sleep(0.5)
    assert not alive(grandchild)


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


def test_should_show_the_model_the_timeout_in_the_fix_round(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeout = "PYTEST:\nTIMEOUT: tests did not finish in 300 s (a test may hang)"
    model = FakeModel()
    implement(repo, monkeypatch, model, FakeChecks((False, timeout), (True, "")))
    fix = [p for p in model.prompts("src/new.py") if "## The checks failed" in p]
    assert fix
    assert "TIMEOUT: tests did not finish" in fix[0]


EDIT_A = "<<<<<<< SEARCH\nA = 1\n=======\n{new}\n>>>>>>> REPLACE"


def test_should_call_a_formatting_only_edit_no_change(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel({"src/old.py": EDIT_A.format(new="A  =  1")})
    code, summary, _ = implement(
        repo, monkeypatch, model, FakeChecks((True, "")), write=["src/old.py"]
    )
    assert (repo / "src" / "old.py").read_text(encoding="utf-8").startswith("A  =  1")
    assert (summary["status"], code, summary["untouched"]) == ("no_change", 1, ["src/old.py"])


def test_should_still_call_an_edit_that_changes_the_code_green(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel({"src/old.py": EDIT_A.format(new="A = 3")})
    _, summary, _ = implement(
        repo, monkeypatch, model, FakeChecks((True, "")), write=["src/old.py"]
    )
    assert (summary["status"], summary["untouched"]) == ("green", [])
