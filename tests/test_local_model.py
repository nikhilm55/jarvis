"""The local-model offload script: its parsing and its guards (no network, no model)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
