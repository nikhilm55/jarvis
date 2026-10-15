"""The local-model offload script: its parsing and its guards (no network, no model)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
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
PLAN = {"files": {"src/new.py": ["def f() -> int"]}, "tests": [{"requirement": "1", "test": "a"}]}
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
        match = re.search(r"(?:Write the \w+|Fix) .*?`([^`]+)`", user)
        rel = match.group(1) if match else ""
        default = fenced(TEST_SRC if rel.startswith("tests/") else IMPL_SRC)
        return self.answer(rel, default)

    def prompts(self, rel: str) -> list[str]:
        return [u for _, u in self.calls if re.search(rf"(?:Write the \w+|Fix) .*?`{rel}`", u)]


class FakeChecks:
    """Stands in for `check`: returns the scripted results in order, then the last one."""

    def __init__(self, *results: tuple[bool, str]) -> None:
        self.results = list(results)
        self.runs = 0

    def __call__(self, repo: Path, files: list[str], tests: list[str], cache: Path) -> object:
        self.runs += 1
        return self.results[min(self.runs, len(self.results)) - 1]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "old.py").write_text("A = 1\nB = 2\n", encoding="utf-8")
    return root


def implement(
    repo: Path, monkeypatch: pytest.MonkeyPatch, model: FakeModel, checks: FakeChecks, **kw: Any
) -> tuple[int, dict[str, Any], Path]:
    """Run `implement`; returns (exit code, summary.json, log dir)."""
    log: Path = kw.pop("log", repo.parent / "log")
    write: list[str] = kw.pop("write", ["tests/test_new.py", "src/new.py"])
    (repo.parent / "brief.md").write_text("brief: make f()", encoding="utf-8")
    argv = ["implement", "--repo", str(repo), "--spec", str(repo.parent / "brief.md")]
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
    assert all(system.startswith(system_md) for system, _ in model.calls)
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


def test_should_fix_a_test_file_once_per_round_when_it_fails_to_collect(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = "PYTEST:\nERROR collecting tests/test_new.py\nImportError: nope"
    model = FakeModel()
    implement(repo, monkeypatch, model, FakeChecks((False, broken), (True, "")))
    assert len(model.prompts("tests/test_new.py")) == 2


@pytest.mark.parametrize(
    ("weaker", "word"),
    [
        ("def test_a() -> None:\n    assert 1\n", "asserts"),
        ("import pytest\n\n\n@pytest.mark.skip\n" + TEST_SRC, "skip"),
    ],
)
def test_should_restore_a_test_file_that_got_weaker_and_report_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch, weaker: str, word: str
) -> None:
    broken = "PYTEST:\nERROR collecting tests/test_new.py\nImportError: nope"
    model = FakeModel({"tests/test_new.py": [fenced(TEST_SRC), fenced(weaker)]})
    checks = FakeChecks((False, broken), (False, broken + " again"))
    code, summary, _ = implement(repo, monkeypatch, model, checks, rounds=1)
    assert (repo / "tests" / "test_new.py").read_text(encoding="utf-8") == TEST_SRC
    [event] = summary["weakening_events"]
    assert (event["file"], event["round"], word in event["problems"][0]) == (
        "tests/test_new.py",
        1,
        True,
    )
    assert summary["tests_locked_counts"]["tests/test_new.py"]["asserts"] == 2
    assert (code, summary["status"]) == (1, "test_weakened")


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
