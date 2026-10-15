"""The local-model offload script: its parsing and its guards (no network, no model)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("local_model", ROOT / "scripts" / "local_model.py")
assert spec and spec.loader
local_model = importlib.util.module_from_spec(spec)
sys.modules["local_model"] = local_model
spec.loader.exec_module(local_model)


def test_should_take_the_last_code_block_when_the_reply_has_several() -> None:
    reply = "draft:\n```python\nx = 1\n```\nfinal:\n```python\nx = 2\n```\n"
    assert local_model.last_code_block(reply) == "x = 2\n"


def test_should_return_none_when_the_reply_has_no_code_block() -> None:
    assert local_model.last_code_block("I can't do that.") is None


def test_should_keep_only_the_last_lines_when_trimming() -> None:
    assert local_model.trim("a\nb\nc\n", lines=2) == "b\nc"


def test_should_refuse_paths_outside_the_repo(tmp_path: Path) -> None:
    assert local_model.inside_repo(tmp_path, "src/jarvis/x.py")
    assert not local_model.inside_repo(tmp_path, "../elsewhere.py")
    assert not local_model.inside_repo(tmp_path, "/etc/passwd")


def test_should_exit_2_without_writing_when_a_write_path_leaves_the_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    brief = tmp_path / "brief.md"
    brief.write_text("task", encoding="utf-8")
    argv = ["implement", "--repo", str(tmp_path), "--spec", str(brief)]
    argv += ["--write", "../outside.py", "--test", "tests", "--log-dir", str(tmp_path / "log")]
    assert local_model.main(argv) == 2
    assert "outside the repo" in capsys.readouterr().err
    assert not (tmp_path / "log").exists()


def test_should_exit_2_when_no_endpoint_is_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    assert local_model.main(["ask", "hello"]) == 2
    assert "LOCAL_LLM_URL" in capsys.readouterr().err


# --- the implement loop (a fake model and fake checks; real git in a temp repo) -----------------

TEST_SRC = "def test_a() -> None:\n    assert 1\n    assert 2\n"
IMPL_SRC = "def f() -> int:\n    return 1\n"
MANIFEST = [
    "tests/test_new.py",
    "src/new.py",
    "src/old.py",
    "tests/test_old.py",
    "src/a.py",
    "src/b.py",
    "scripts/tool.py",
    "src/helpers.py",
    "src/other.py",
]
PLAN = {
    "files": {name: ["def f() -> int"] for name in MANIFEST},
    "tests": [{"requirement": "1", "test": "test_a"}],
}
MET = json.dumps([{"requirement": "1", "status": "met", "note": "ok"}])
FAILED = "PYTEST:\nFAILED tests/test_new.py::test_a - assert 0"


def fenced(code: str) -> str:
    return f"```python\n{code}```"


class FakeModel:
    """Stands in for `chat`: answers by the kind of call, records every (system, user) pair."""

    def __init__(self, replies: dict[str, str | list[str]] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[tuple[str, str]] = []

    def answer(self, key: str, default: str) -> str:
        """A list is consumed in order (the last item repeats); a string is always the answer."""
        value = self.replies.get(key, default)
        return (value.pop(0) if len(value) > 1 else value[0]) if isinstance(value, list) else value

    def __call__(self, messages: list[dict[str, str]], max_tokens: int, timeout: int) -> str:
        system, user = messages[0]["content"], messages[-1]["content"]
        self.calls.append((system, user))
        if "JSON object" in system:
            return self.answer("plan", json.dumps(PLAN))
        if system.startswith(local_model.REVIEW_SYSTEM):
            return self.answer("review", MET)
        match = re.search(r"(?:Write the \w+|Fix) .*?`([^`]+)`", user)
        rel = match.group(1) if match else ""
        default = fenced(TEST_SRC if rel.startswith("tests/") else IMPL_SRC)
        return self.answer(rel, default)

    def prompts(self, rel: str) -> list[str]:
        return [u for _, u in self.calls if re.search(rf"(?:Write the \w+|Fix) .*?`{rel}`", u)]


class FakeChecks:
    """Stands in for `check`: returns the scripted results in order, then the last one."""

    def __init__(self, *results: tuple[bool, str], effect: Callable[[Path], None] | None = None):
        self.results = list(results)
        self.effect = effect
        self.runs = 0

    def __call__(self, repo: Path, files: list[str], tests: list[str], cache: Path) -> object:
        if self.effect:
            self.effect(repo)
        self.runs += 1
        return self.results[min(self.runs, len(self.results)) - 1]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture(autouse=True)
def clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under a git hook GIT_DIR points at the outer repo; the temp repos must not see it."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "old.py").write_text("A = 1\nB = 2\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return root


def implement(
    repo: Path, monkeypatch: pytest.MonkeyPatch, model: FakeModel, checks: FakeChecks, **kw: Any
) -> tuple[int, dict[str, Any], Path]:
    """Run `implement`; returns (exit code, summary.json, log dir)."""
    home: Path = kw.pop("home", repo.parent)  # where the brief and the log live
    log: Path = kw.pop("log", home / "log")
    write: list[str] = kw.pop("write", ["tests/test_new.py", "src/new.py"])
    (home / "brief.md").write_text(kw.pop("brief", "brief: make f()"), encoding="utf-8")
    argv = ["implement", "--repo", str(repo), "--spec", str(home / "brief.md")]
    argv += [
        "--write",
        *write,
        "--test",
        "tests",
        "--log-dir",
        str(log),
        "--rounds",
        str(kw.pop("rounds", 3)),
    ]
    monkeypatch.setattr(local_model, "chat", model)
    monkeypatch.setattr(local_model, "check", checks)
    code = local_model.main(argv)
    return code, json.loads((log / "summary.json").read_text(encoding="utf-8")), log


def test_should_plan_first_with_the_system_prompt_from_the_harness_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel()
    _, summary, log = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    system_md = local_model.SYSTEM_FILE.read_text(encoding="utf-8")
    assert system_md.strip()
    assert all(system.startswith(system_md) for system, _ in model.calls[:-1])  # not the review
    assert "JSON object" in model.calls[0][0]
    assert "ONE fenced" in model.calls[1][0]
    assert json.loads((log / "plan.json").read_text(encoding="utf-8")) == PLAN
    assert summary["plan"] is True
    assert all("def f() -> int" in user for _, user in model.calls[1:])
    assert (repo / "src" / "new.py").read_text(encoding="utf-8") == IMPL_SRC


def test_should_retry_the_plan_once_then_continue_without_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel({"plan": "not json at all"})
    _, summary, log = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert sum("JSON object" in system for system, _ in model.calls) == 2
    assert summary["plan"] is False
    assert not (log / "plan.json").exists()
    assert (repo / "src" / "new.py").read_text(encoding="utf-8") == IMPL_SRC


def test_should_draft_the_tests_first_and_only_fix_implementation_files(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel()
    code, summary, _ = implement(
        repo,
        monkeypatch,
        model,
        FakeChecks((False, FAILED), (True, "")),
        write=["src/new.py", "tests/test_new.py"],
    )
    kinds = [re.search(r"(Write the \w+|Fix) .*?`([^`]+)`", u) for _, u in model.calls[1:]]
    assert [m.groups()[1] for m in kinds if m] == ["tests/test_new.py", "src/new.py", "src/new.py"]
    assert not model.prompts("tests/test_new.py")[1:]
    assert summary["rounds"] == 1
    assert code == 0


def broken(n: int = 0) -> str:
    """A pytest report where tests/test_new.py fails to import `src` (its own mistake)."""
    return (
        "PYTEST:\n___ ERROR collecting tests/test_new.py ___\n"
        "tests/test_new.py:1: in <module>\n    from src.new import f\n"
        "E   ModuleNotFoundError: No module named 'src'\n"
        f"=== short test summary info ===\nERROR tests/test_new.py - x\nFAILED t.py::t{n}"
    )


def no_name(module: str) -> str:
    return (
        "PYTEST:\n___ ERROR collecting tests/test_new.py ___\ntests/test_new.py:1: in <module>\n"
        f"    from {module} import g\nE   ImportError: cannot import name 'g' from '{module}'\n"
        "=== short test summary info ===\nERROR tests/test_new.py - ImportError: no name 'g'"
    )


LINT = "MYPY:\ntests/test_new.py:3: error: bad  [misc]"


def test_should_fix_a_test_file_when_its_own_import_fails_to_collect(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel()
    implement(repo, monkeypatch, model, FakeChecks((False, broken()), (True, "")))
    [_, fix] = model.prompts("tests/test_new.py")
    assert "only the import lines" in fix


@pytest.mark.parametrize(
    ("impl", "module"), [("src/new.py", "jarvis.new"), ("scripts/tool.py", "tool")]
)
def test_should_blame_the_implementation_when_it_lacks_a_name_the_test_imports(
    repo: Path, monkeypatch: pytest.MonkeyPatch, impl: str, module: str
) -> None:
    model = FakeModel(
        {"tests/test_new.py": [fenced(TEST_SRC), fenced("def test_a():\n    assert True\n")]}
    )
    checks = FakeChecks((False, no_name(module)), (True, ""))
    code, summary, _ = implement(
        repo, monkeypatch, model, checks, write=["tests/test_new.py", impl]
    )
    assert len(model.prompts("tests/test_new.py")) == 1
    assert "no name 'g'" in model.prompts(impl)[1]
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == TEST_SRC
    assert (code, summary["weakening_events"]) == (0, [])


TYPO = "from jarvis.helpres import f\n\n\ndef test_a() -> None:\n    assert f() == 1\n"


def test_should_allow_one_import_path_fix_to_a_manifest_module_and_no_second_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = TYPO.replace("helpres", "helpers")
    again = TYPO.replace("helpres", "other")
    model = FakeModel({"tests/test_new.py": [fenced(TYPO), fenced(fixed), fenced(again)]})
    checks = FakeChecks((False, broken(1)), (False, broken(2)), (False, broken(3)))
    write = ["tests/test_new.py", "src/helpers.py", "src/other.py"]
    _, summary, _ = implement(repo, monkeypatch, model, checks, write=write, rounds=2)
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == fixed
    assert [(e["round"], e["file"]) for e in summary["weakening_events"]] == [
        (2, "tests/test_new.py")
    ]
    assert "rebound" in summary["weakening_events"][0]["problems"][0]


ASSERT_TRUE = "def test_a() -> None:\n    assert True\n    assert 2\n"


@pytest.mark.parametrize(
    ("weaker", "word"),
    [
        ("def test_a() -> None:\n    assert 1\n", "asserts"),
        ("import pytest\n\n\n@pytest.mark.skip\n" + TEST_SRC, "skip"),
        (ASSERT_TRUE, "locked statement"),
        ("def test_a(:\n", "does not parse"),
    ],
)
def test_should_restore_a_test_file_that_got_weaker_and_report_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch, weaker: str, word: str
) -> None:
    model = FakeModel({"tests/test_new.py": [fenced(TEST_SRC), fenced(weaker)]})
    checks = FakeChecks((False, broken(1)), (True, ""))
    code, summary, _ = implement(repo, monkeypatch, model, checks)
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == TEST_SRC
    [event] = summary["weakening_events"]
    assert (event["file"], event["round"]) == ("tests/test_new.py", 1)
    assert any(word in problem for problem in event["problems"])
    assert summary["tests_locked_counts"]["tests/test_new.py"]["asserts"] == 2
    assert (code, summary["status"]) == (1, "test_weakened")


def test_should_restore_the_last_locked_content_and_prefer_test_weakened_to_stalled(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weak = [fenced(ASSERT_TRUE), fenced("def test_a() -> None:\n    assert 2\n")]
    model = FakeModel({"tests/test_new.py": [fenced(TEST_SRC), *weak]})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((False, broken())))
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == TEST_SRC
    assert [e["round"] for e in summary["weakening_events"]] == [1]
    assert (code, summary["status"]) == (1, "test_weakened")


def test_should_hold_an_existing_test_file_to_its_pre_run_content_in_round_0(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = "def test_x() -> None:\n    assert 1\n\n\ndef test_y() -> None:\n    assert 2\n"
    (repo / "tests" / "test_old.py").write_text(old, encoding="utf-8")
    drop = "<<<<<<< SEARCH\n\n\ndef test_y() -> None:\n    assert 2\n=======\n>>>>>>> REPLACE\n"
    model = FakeModel({"tests/test_old.py": drop})
    code, summary, _ = implement(
        repo, monkeypatch, model, FakeChecks((True, "")), write=["tests/test_old.py"]
    )
    assert (repo / "tests" / "test_old.py").read_text(encoding="utf-8") == old
    assert [e["round"] for e in summary["weakening_events"]] == [0]
    assert (code, summary["status"]) == (1, "test_weakened")


def test_should_let_an_existing_test_file_gain_a_new_test_in_round_0(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "tests" / "test_old.py").write_text(TEST_SRC, encoding="utf-8")
    more = (
        "<<<<<<< SEARCH\n    assert 2\n=======\n    assert 2\n\n\n"
        "def test_b() -> None:\n    assert 3\n>>>>>>> REPLACE\n"
    )
    model = FakeModel({"tests/test_old.py": more})
    code, summary, _ = implement(
        repo, monkeypatch, model, FakeChecks((True, "")), write=["tests/test_old.py"]
    )
    assert "def test_b" in (repo / "tests" / "test_old.py").read_text(encoding="utf-8")
    assert "existing tests are locked" in model.prompts("tests/test_old.py")[0]
    assert (code, summary["weakening_events"]) == (0, [])


def test_should_give_a_test_file_one_lint_round_that_may_only_change_annotations(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    untyped = TEST_SRC.replace(" -> None", "")
    model = FakeModel({"tests/test_new.py": [fenced(TEST_SRC), fenced(untyped)]})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((False, LINT), (True, "")))
    assert "only the type annotations and imports" in model.prompts("tests/test_new.py")[1]
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == untyped
    assert (code, summary["weakening_events"], model.prompts("src/new.py")[1:]) == (0, [], [])


@pytest.mark.parametrize(
    ("reply", "status"),
    [(TEST_SRC.replace(" -> None", " -> int"), "test_error"), (ASSERT_TRUE, "test_weakened")],
)
def test_should_stop_after_the_one_lint_round_whether_or_not_it_kept_the_lock(
    repo: Path, monkeypatch: pytest.MonkeyPatch, reply: str, status: str
) -> None:
    model = FakeModel({"tests/test_new.py": [fenced(TEST_SRC), fenced(reply)]})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((False, LINT)))
    assert len(model.prompts("tests/test_new.py")) == 2
    assert (code, summary["status"], summary["rounds"]) == (1, status, 1)


def test_should_collect_test_disputes_and_end_as_test_disputed_when_stalled(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispute = fenced(IMPL_SRC) + "\nTEST-DISPUTE: the test expects 'supercali' for max_len=10\n"
    model = FakeModel({"src/new.py": dispute})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((False, FAILED)))
    assert (code, summary["status"]) == (1, "test_disputed")
    assert summary["test_disputes"][0]["file"] == "src/new.py"
    assert "supercali" in summary["test_disputes"][0]["text"]


def test_should_edit_an_existing_file_with_blocks_and_send_a_rejected_one_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = "<<<<<<< SEARCH\nB = 99\n=======\nB = 3\n>>>>>>> REPLACE\n"
    good = "<<<<<<< SEARCH\nB = 2\n=======\nB = 3\n>>>>>>> REPLACE\n"
    model = FakeModel({"src/old.py": [bad, good]})
    mypy = "MYPY:\nsrc/old.py:2: error: bad  [misc]"
    checks = FakeChecks((False, mypy), (True, ""))
    implement(repo, monkeypatch, model, checks, write=["src/old.py"])
    first, second = model.prompts("src/old.py")
    assert "edit 1: SEARCH not found" in second
    assert "SEARCH not found" not in first
    assert "SEARCH/REPLACE" in model.calls[1][0]
    assert (repo / "src" / "old.py").read_text(encoding="utf-8") == "A = 1\nB = 3\n"


def test_should_edit_a_file_over_150_lines_in_a_fix_round_even_when_the_run_created_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = "".join(f"X{i} = {i}\n" for i in range(160))
    edit = "<<<<<<< SEARCH\nX5 = 5\n=======\nX5 = 50\n>>>>>>> REPLACE\n"
    model = FakeModel({"src/new.py": [fenced(big), edit]})
    mypy = "MYPY:\nsrc/new.py:5: error: bad  [misc]"
    implement(repo, monkeypatch, model, FakeChecks((False, mypy), (True, "")))
    [fix_system] = [system for system, user in model.calls if "Fix `src/new.py`" in user]
    assert "SEARCH/REPLACE" in fix_system
    assert "X5 = 50\n" in (repo / "src" / "new.py").read_text(encoding="utf-8")


def test_should_stop_on_scope_violation_and_leave_the_stray_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stray(root: Path) -> None:
        (root / "stray.txt").write_text("oops", encoding="utf-8")

    code, summary, _ = implement(
        repo, monkeypatch, FakeModel(), FakeChecks((False, FAILED), effect=stray)
    )
    assert (code, summary["status"]) == (1, "scope_violation")
    assert summary["scope_violations"] == ["stray.txt"]
    assert (repo / "stray.txt").exists()
    assert (repo / "src" / "new.py").exists()


def test_should_ignore_files_dirty_before_the_run_and_the_log_dir_inside_the_repo(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "src" / "old.py").write_text("A = 9\n", encoding="utf-8")
    code, summary, _ = implement(
        repo, monkeypatch, FakeModel(), FakeChecks((True, "")), log=repo / ".runs" / "x"
    )
    assert (code, summary["status"]) == (0, "green")


def test_should_stop_as_stalled_when_the_same_failure_repeats(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel()
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((False, FAILED)))
    assert (code, summary["status"], summary["rounds"]) == (1, "stalled", 1)
    assert len(model.prompts("src/new.py")) == 2


def test_should_send_each_file_only_the_errors_that_mention_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = "RUFF:\nsrc/a.py:1:1: F401 unused\nsrc/b.py:2:1: E501 long\n\n" + FAILED
    model = FakeModel()
    write = ["tests/test_new.py", "src/a.py", "src/b.py"]
    implement(repo, monkeypatch, model, FakeChecks((False, report), (True, "")), write=write)
    to_a, to_b = model.prompts("src/a.py")[1], model.prompts("src/b.py")[1]
    assert "src/a.py:1:1" in to_a
    assert "src/b.py:2:1" not in to_a
    assert "src/b.py:2:1" in to_b
    assert "FAILED tests/test_new.py::test_a" in to_a
    assert "FAILED tests/test_new.py::test_a" in to_b


def test_should_review_green_work_in_a_fresh_context_and_list_missing_requirements(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [
        {"requirement": "1", "status": "met", "note": "ok"},
        {"requirement": "2", "status": "missing", "note": "no test"},
    ]
    model = FakeModel({"review": json.dumps(items)})
    code, summary, log = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    system, user = model.calls[-1]
    assert system.startswith(local_model.REVIEW_SYSTEM)
    assert "def f() -> int" in user
    assert "Write the" not in user
    assert json.loads((log / "review.json").read_text(encoding="utf-8")) == items
    assert summary["review_missing"] == ["2"]
    assert (code, summary["status"]) == (1, "green")
    assert (repo / "src" / "new.py").read_text(encoding="utf-8") == IMPL_SRC


def test_should_exit_0_when_green_and_nothing_is_missing_and_skip_review_when_red(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    met = json.dumps([{"requirement": "1", "status": "met", "note": "ok"}])
    code, summary, _ = implement(
        repo, monkeypatch, FakeModel({"review": met}), FakeChecks((True, ""))
    )
    assert (code, summary["review_missing"]) == (0, [])
    model = FakeModel()
    _, red, log = implement(
        repo, monkeypatch, model, FakeChecks((False, "RUFF:\nx.py:1:1: E1 a")), rounds=0
    )
    assert red["status"] == "red"
    assert not (log / "review.json").exists() or red["review_missing"] == []
    assert not any(system.startswith(local_model.REVIEW_SYSTEM) for system, _ in model.calls)


def test_should_exit_2_when_the_repo_is_not_a_git_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (tmp_path / "brief.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(local_model, "chat", FakeModel())
    argv = ["implement", "--repo", str(plain), "--spec", str(tmp_path / "brief.md")]
    argv += ["--write", "a.py", "--test", "t", "--log-dir", str(tmp_path / "log")]
    assert local_model.main(argv) == 2
    assert "git repository" in capsys.readouterr().err


def test_should_write_a_new_file_whole(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel()
    implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert "SEARCH/REPLACE" not in model.calls[2][0]
    assert (repo / "src" / "new.py").read_text(encoding="utf-8") == IMPL_SRC


def test_should_write_every_summary_field(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, summary, _ = implement(repo, monkeypatch, FakeModel(), FakeChecks((True, "")))
    wanted = {"status", "plan", "tests_locked_counts", "weakening_events", "rounds"}
    assert wanted <= summary.keys()


def test_should_keep_ask_a_single_user_prompt_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[list[dict[str, str]]] = []

    def fake(messages: list[dict[str, str]], max_tokens: int, timeout: int) -> str:
        seen.append(messages)
        return " answer \n"

    monkeypatch.setattr(local_model, "chat", fake)
    assert local_model.main(["ask", "hello"]) == 0
    assert capsys.readouterr().out == "answer\n"
    assert seen == [[{"role": "user", "content": "hello"}]]


def test_should_trim_each_routed_error_section_to_its_last_60_lines(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = "\n".join(f"src/new.py:{i}:1: E501 long" for i in range(1, 101))
    model = FakeModel()
    implement(repo, monkeypatch, model, FakeChecks((False, f"RUFF:\n{lines}"), (True, "")))
    fix = model.prompts("src/new.py")[1]
    assert "src/new.py:100:1: E501" in fix
    assert "src/new.py:41:1: E501" in fix
    assert "src/new.py:40:1: E501" not in fix


@pytest.mark.parametrize("name", ["./tests/test_new.py", "tests/../tests/test_new.py", "abs"])
def test_should_lock_a_test_file_named_with_a_dot_or_an_absolute_path(
    repo: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    given = str(repo / "tests" / "test_new.py") if name == "abs" else name
    weaker = fenced(ASSERT_TRUE)
    model = FakeModel({"tests/test_new.py": [fenced(TEST_SRC), weaker]})
    checks = FakeChecks((False, broken(1)), (True, ""))
    code, summary, _ = implement(repo, monkeypatch, model, checks, write=[given, "./src/new.py"])
    assert summary["files"] == ["tests/test_new.py", "src/new.py"]
    assert [e["file"] for e in summary["weakening_events"]] == ["tests/test_new.py"]
    assert (code, summary["scope_violations"]) == (1, [])


def test_should_flag_a_further_edit_to_a_file_that_was_already_dirty(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "notes.txt").write_text("one", encoding="utf-8")

    def touch(root: Path) -> None:
        (root / "notes.txt").write_text("two", encoding="utf-8")

    code, summary, _ = implement(
        repo, monkeypatch, FakeModel(), FakeChecks((False, FAILED), effect=touch)
    )
    assert (code, summary["status"], summary["scope_violations"]) == (
        1,
        "scope_violation",
        ["notes.txt"],
    )


def test_should_work_when_the_repo_is_a_subdirectory_of_the_git_root(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = repo / "sub"
    (sub / "tests").mkdir(parents=True)
    (sub / "src").mkdir()
    code, summary, _ = implement(
        repo=sub,
        monkeypatch=monkeypatch,
        model=FakeModel(),
        checks=FakeChecks((True, "")),
        home=repo.parent,
    )
    assert (code, summary["status"], summary["scope_violations"]) == (0, "green", [])
    assert (sub / "src" / "new.py").exists()


@pytest.mark.parametrize(
    "plan",
    [
        {"files": {}, "tests": []},
        {"files": {"src/new.py": []}, "tests": [{"requirement": "1", "test": "test_a"}]},
        {"files": {name: [] for name in MANIFEST}, "tests": []},
    ],
)
def test_should_not_accept_a_plan_without_every_file_or_without_tests(
    repo: Path, monkeypatch: pytest.MonkeyPatch, plan: dict[str, object]
) -> None:
    model = FakeModel({"plan": json.dumps(plan)})
    _, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert summary["plan"] is False
    assert sum("JSON object" in system for system, _ in model.calls) == 2
    retry = model.calls[1][1]
    assert "tests/test_new.py, src/new.py" in retry


def test_should_list_planned_tests_that_were_never_drafted(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = dict(
        PLAN,
        tests=[{"requirement": "1", "test": "test_a"}, {"requirement": "2", "test": "T::test_zzz"}],
    )
    both = json.dumps([{"requirement": r, "status": "met", "note": "ok"} for r in "12"])
    model = FakeModel({"plan": json.dumps(plan), "review": both})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert (summary["plan_tests_missing"], summary["status"]) == (["test_zzz"], "green")
    assert code == 1


@pytest.mark.parametrize("review", ["no json here", "[]"])
def test_should_exit_1_when_the_review_is_unparseable_or_covers_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, review: str
) -> None:
    code, summary, _ = implement(
        repo, monkeypatch, FakeModel({"review": review}), FakeChecks((True, ""))
    )
    assert (code, summary["status"], summary["review_complete"]) == (1, "green", False)


def test_should_exit_1_when_the_review_covers_fewer_items_than_the_plan_has_requirements(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = dict(
        PLAN, tests=[{"requirement": "1", "test": "test_a"}, {"requirement": "2", "test": "test_a"}]
    )
    code, summary, _ = implement(
        repo, monkeypatch, FakeModel({"plan": json.dumps(plan)}), FakeChecks((True, ""))
    )
    assert (code, summary["review_complete"]) == (1, False)


BRIEF = "## Requirements\n1. does a\n2. does b\n\n## Constraints\n3. not a requirement\n"


def two_reqs_plan(**kw: object) -> str:
    tests = [{"requirement": r, "test": "test_a"} for r in ("1", "2", "extra")]
    return json.dumps(dict(PLAN, tests=kw.get("tests", tests)))


@pytest.mark.parametrize(
    "tests",
    [
        ["test_a"],
        [{"requirement": 1, "test": "test_a"}, {"requirement": 2, "test": "test_a"}],
        [{"requirement": "1", "test": "test_a"}],
        [{"requirement": "one", "test": "test_a"}, {"requirement": "two", "test": "test_a"}],
    ],
)
def test_should_reject_a_plan_that_is_malformed_or_misses_a_numbered_requirement(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tests: list[object]
) -> None:
    model = FakeModel({"plan": two_reqs_plan(tests=tests)})
    _, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")), brief=BRIEF)
    assert summary["plan"] is False
    assert "(1, 2)" in model.calls[1][1]


@pytest.mark.parametrize(("items", "exit_code"), [(1, 1), (2, 0)])
def test_should_count_review_completeness_against_the_briefs_requirements(
    repo: Path, monkeypatch: pytest.MonkeyPatch, items: int, exit_code: int
) -> None:
    review = json.dumps(
        [{"requirement": str(i), "status": "met", "note": "ok"} for i in range(items)]
    )
    model = FakeModel({"plan": two_reqs_plan(), "review": review})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")), brief=BRIEF)
    assert (code, summary["plan"]) == (exit_code, True)


def test_should_restore_a_test_file_that_is_tampered_with_during_the_final_check(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[int] = []

    def tamper(root: Path) -> None:
        runs.append(1)
        if len(runs) == 2:  # the check that ends the first fix round
            (root / "tests" / "test_new.py").write_text(ASSERT_TRUE, encoding="utf-8")

    checks = FakeChecks((False, FAILED), (True, ""), effect=tamper)
    code, summary, _ = implement(repo, monkeypatch, FakeModel(), checks)
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == TEST_SRC
    assert [e["round"] for e in summary["weakening_events"]] == [1]
    assert (code, summary["status"]) == (1, "test_weakened")


DISARM = "import _pytest.python as p\n\np.Function.runtest = lambda self: None\n"


def test_should_remove_a_new_implementation_file_that_imports_pytest_and_stop_as_sensor_tamper(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel({"src/new.py": fenced("import pytest\n" + IMPL_SRC)})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((True, "")))
    assert not (repo / "src" / "new.py").exists()
    assert [(e["round"], e["file"]) for e in summary["tamper_events"]] == [(0, "src/new.py")]
    assert (code, summary["status"]) == (1, "sensor_tamper")


def test_should_restore_the_last_good_implementation_when_a_fix_disarms_pytest(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel({"src/new.py": [fenced(IMPL_SRC), fenced(IMPL_SRC + DISARM)]})
    code, summary, _ = implement(repo, monkeypatch, model, FakeChecks((False, FAILED), (True, "")))
    assert (repo / "src" / "new.py").read_text(encoding="utf-8") == IMPL_SRC
    assert [e["round"] for e in summary["tamper_events"]] == [1]
    assert (code, summary["status"]) == (1, "sensor_tamper")


def test_should_restore_an_existing_implementation_file_to_its_pre_run_content(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edit = "<<<<<<< SEARCH\nB = 2\n=======\nB = 2\nimport unittest.mock\n>>>>>>> REPLACE\n"
    model = FakeModel({"src/old.py": edit})
    code, summary, _ = implement(
        repo, monkeypatch, model, FakeChecks((True, "")), write=["src/old.py"]
    )
    assert (repo / "src" / "old.py").read_text(encoding="utf-8") == "A = 1\nB = 2\n"
    assert (code, summary["status"]) == (1, "sensor_tamper")
