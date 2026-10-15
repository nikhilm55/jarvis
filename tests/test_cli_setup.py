"""Tests for `jarvis setup` and the `jarvis run` name tip. JARVIS_HOME is a tmp dir (conftest)."""

import tomllib
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.config import load_settings
from jarvis.paths import config_dir
from tests.core_rig import CoreRig
from tests.listener_rig import seg
from tests.test_cli_run import Hook


def _config() -> Path:
    return config_dir() / "config.toml"


def _answer(monkeypatch: pytest.MonkeyPatch, text: str) -> list[str]:
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return text

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_should_set_the_name_when_given_name_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["setup", "--name", "  Nikhil "]) == 0
    assert tomllib.loads(_config().read_text(encoding="utf-8")) == {"user": {"name": "Nikhil"}}
    assert load_settings().user.name == "Nikhil"
    assert capsys.readouterr().out == "Jarvis will call you Nikhil.\n"


def test_should_change_only_the_name_line_of_an_existing_config() -> None:
    original = '# mine\n[brain]\nmodel = "opus"\n\n[user]\nname = "Old"\n'
    _config().parent.mkdir(parents=True)
    _config().write_text(original, encoding="utf-8")
    assert cli.main(["setup", "--name", "New"]) == 0
    assert _config().read_text(encoding="utf-8") == original.replace("Old", "New")


def test_should_clear_the_name_when_given_clear_name_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["setup", "--name", "Nikhil"])
    capsys.readouterr()
    assert cli.main(["setup", "--clear-name"]) == 0
    assert load_settings().user.name is None
    assert capsys.readouterr().out == "Jarvis will not address you by name.\n"


def test_should_create_nothing_when_clearing_a_name_that_was_never_set() -> None:
    assert cli.main(["setup", "--clear-name"]) == 0
    assert not _config().exists()


def test_should_ask_for_the_name_and_save_the_answer_when_given_no_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts = _answer(monkeypatch, "Ana")
    assert cli.main(["setup"]) == 0
    assert prompts == ["What should Jarvis call you? "]
    assert load_settings().user.name == "Ana"
    assert capsys.readouterr().out == "Jarvis will call you Ana.\n"


@pytest.mark.parametrize("answer", ["", "   "])
def test_should_leave_the_name_unchanged_when_the_answer_is_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], answer: str
) -> None:
    cli.main(["setup", "--name", "Nikhil"])
    capsys.readouterr()
    _answer(monkeypatch, answer)
    assert cli.main(["setup"]) == 0
    assert load_settings().user.name == "Nikhil"
    assert capsys.readouterr().out == "Name left unchanged.\n"


def test_should_leave_the_name_unchanged_when_input_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def closed(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert cli.main(["setup"]) == 0
    assert not _config().exists()


@pytest.mark.parametrize("bad", ["", "   ", "a" * 41, "a\nb"])
def test_should_exit_2_with_a_message_and_write_nothing_when_the_name_is_bad(
    capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    assert cli.main(["setup", "--name", bad]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("jarvis setup: ")
    assert captured.out == ""
    assert not _config().exists()


def test_should_exit_2_and_leave_the_file_when_the_config_is_not_valid_toml(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config().parent.mkdir(parents=True)
    _config().write_text("[audio\n", encoding="utf-8")
    assert cli.main(["setup", "--name", "Ana"]) == 2
    assert "not valid TOML" in capsys.readouterr().err
    assert _config().read_text(encoding="utf-8") == "[audio\n"


def test_should_reject_name_and_clear_name_together() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup", "--name", "Ana", "--clear-name"])
    assert exit_info.value.code == 2


def test_should_remove_a_leftover_address_as_and_say_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = '[brain]\nmodel = "opus"\naddress_as = "Boss"\n'
    _config().parent.mkdir(parents=True)
    _config().write_bytes(original.encode())
    assert cli.main(["setup", "--name", "Nik"]) == 0
    assert _config().read_bytes() == b'[brain]\nmodel = "opus"\n\n[user]\nname = "Nik"\n'
    assert capsys.readouterr().out == (
        "Jarvis will call you Nik.\nRemoved the old brain.address_as setting from config.toml.\n"
    )
    assert load_settings().user.name == "Nik"  # the config loads again


def test_should_tell_the_user_to_delete_address_as_when_it_cannot_be_removed_safely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = '[brain]\naddress_as = """\nBoss\n"""\n'
    _config().parent.mkdir(parents=True)
    _config().write_bytes(original.encode())
    assert cli.main(["setup", "--name", "Nik"]) == 0
    assert _config().read_bytes() == (original + '\n[user]\nname = "Nik"\n').encode()
    assert "delete that line" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["a\udcffb", "a\u202eb", "a\u2028b"])
def test_should_exit_2_without_a_traceback_for_a_name_the_terminal_mangled(
    capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    # argv can carry a lone surrogate (invalid UTF-8 bytes); it must be refused, not crash
    assert cli.main(["setup", "--name", bad]) == 2
    assert capsys.readouterr().err.startswith("jarvis setup: ")
    assert not _config().exists()


def test_should_exit_2_with_a_remedy_when_the_config_is_not_utf8(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config().parent.mkdir(parents=True)
    _config().write_bytes(b'[user]\nname = "\xff"\n')
    assert cli.main(["setup", "--name", "Ana"]) == 2
    assert "save it as UTF-8" in capsys.readouterr().err
    assert _config().read_bytes() == b'[user]\nname = "\xff"\n'


def test_should_exit_2_when_the_config_cannot_be_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config().mkdir(parents=True)  # a folder where the file should be
    assert cli.main(["setup", "--name", "Ana"]) == 2
    assert capsys.readouterr().err.startswith("jarvis setup: ")


def _run_with_no_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    rig = CoreRig(tmp_path, ["Jarvis, set the volume to 40"], with_brain=False)
    rig.feed.push(seg())
    rig.feed.end()
    monkeypatch.setattr(cli, "build_components", Hook(rig.parts))
    code = cli.main(["run", "--source", str(tmp_path / "meeting.wav"), "--no-brain", "--no-hud"])
    assert code == 0
    return capsys.readouterr().out


def test_should_print_the_name_tip_once_when_running_with_no_name_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_with_no_brain(tmp_path, monkeypatch, capsys)
    assert out.count("Tip: tell Jarvis your name with: jarvis setup --name <your name>\n") == 1
    assert out.startswith("Tip:")


def test_should_not_print_the_name_tip_when_a_name_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["setup", "--name", "Nikhil"])
    capsys.readouterr()
    assert "Tip:" not in _run_with_no_brain(tmp_path, monkeypatch, capsys)
