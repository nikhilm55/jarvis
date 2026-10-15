"""Tests for the jarvis.desktop.apps module."""

import sys
from pathlib import Path

import pytest

from jarvis.desktop.apps import (
    Ambiguous,
    AppEntry,
    application_dirs,
    find_app,
    load_index,
)

FIXTURES = Path(__file__).parent / "fixtures" / "desktop"
SHARE = FIXTURES / "share"
HOME = FIXTURES / "home"


def _index() -> list[AppEntry]:
    return load_index([SHARE / "applications"])


@pytest.mark.parametrize(
    "desktop_id",
    ["hidden-app.desktop", "gone.desktop", "some-link.desktop", "broken.desktop"],
)
def test_should_skip_entry_when_entry_is_invalid(desktop_id: str) -> None:
    entries = _index()
    assert not any(e.desktop_id == desktop_id for e in entries)


def test_should_build_nested_id_when_file_is_in_subdir() -> None:
    entries = _index()
    nested = next(e for e in entries if e.desktop_id == "sub-nested.desktop")
    assert nested.name == "Nested Tool"


def test_should_ignore_localised_name_when_name_key_is_localised() -> None:
    entries = _index()
    browser = next(e for e in entries if e.desktop_id == "browser.desktop")
    assert browser.name == "Browser"


def test_should_ignore_action_section_when_section_is_action() -> None:
    entries = _index()
    browser = next(e for e in entries if e.desktop_id == "browser.desktop")
    assert browser.name == "Browser"


@pytest.mark.parametrize(
    ("desktop_id", "expected"),
    [
        ("org.example.Calculator.desktop", "examplecalc"),
        ("org.example.TextEditor.desktop", "texted"),
    ],
)
def test_should_return_exec_name_when_exec_is_parsed(desktop_id: str, expected: str) -> None:
    entries = _index()
    entry = next(e for e in entries if e.desktop_id == desktop_id)
    assert entry.exec_name == expected


def test_should_parse_startup_wm_class_when_present() -> None:
    entries = _index()
    calc = next(e for e in entries if e.desktop_id == "org.example.Calculator.desktop")
    assert calc.startup_wm_class == "ExampleCalc"


def test_should_parse_keywords_when_present() -> None:
    entries = _index()
    editor = next(e for e in entries if e.desktop_id == "org.example.TextEditor.desktop")
    assert editor.keywords == ("notepad", "writing")


def test_should_shadow_share_when_home_dir_is_first() -> None:
    entries = load_index([HOME / "applications", SHARE / "applications"])
    calc = next(e for e in entries if e.desktop_id == "org.example.Calculator.desktop")
    assert calc.name == "Calculator"
    assert calc.exec_name == "usercalc"


def test_should_ignore_missing_dir_when_dir_does_not_exist() -> None:
    entries = load_index([Path("/nonexistent/dir"), SHARE / "applications"])
    assert any(e.desktop_id == "org.example.Calculator.desktop" for e in entries)


def test_should_use_defaults_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_DIRS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    dirs = application_dirs()
    assert dirs[0] == tmp_path / ".local" / "share" / "applications"
    assert Path("/usr/local/share/applications") in dirs
    assert Path("/usr/share/applications") in dirs


@pytest.mark.skipif(sys.platform != "linux", reason="XDG_DATA_DIRS is a colon-separated POSIX list")
def test_should_use_env_dirs_when_env_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "a") + ":" + str(tmp_path / "b"))
    dirs = application_dirs()
    assert dirs == [
        tmp_path / "xdg" / "applications",
        tmp_path / "a" / "applications",
        tmp_path / "b" / "applications",
    ]


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("CALCULATOR", "Calculator"),
        ("org.example.Calculator.desktop", "Calculator"),
        ("org.example.Calculator", "Calculator"),
        ("notepad", "Text Editor"),
        ("calc", "Calculator"),
        ("editor", "Text Editor"),
        ("terminal one", "Terminal One"),
    ],
)
def test_should_find_app_when_query_matches(query: str, expected_name: str) -> None:
    result = find_app(query, _index())
    assert isinstance(result, AppEntry)
    assert result.name == expected_name


def test_should_return_ambiguous_when_multiple_match() -> None:
    result = find_app("terminal", _index())
    assert isinstance(result, Ambiguous)
    names = [e.name for e in result.candidates]
    assert names == ["Terminal One", "Terminal Two"]


@pytest.mark.parametrize("query", ["", "   ", "nonexistentapp", "hidden helper"])
def test_should_return_none_when_query_is_invalid(query: str) -> None:
    assert find_app(query, _index()) is None


def test_should_use_load_index_when_entries_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "nonexistent"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(SHARE))
    result = find_app("calculator")
    assert isinstance(result, AppEntry)
    assert result.name == "Calculator"


def _entry(exec_line: str) -> AppEntry:
    return AppEntry("x.desktop", "X", "", (), exec_line, "", Path("x.desktop"))


@pytest.mark.parametrize(
    ("exec_line", "expected"),
    [
        ("FOO=bar prog --flag", "FOO=bar"),
        ("env A=1 B=2 /opt/app/run %U", "run"),
        ("env", ""),
        ('prog "unterminated', ""),
        ("", ""),
    ],
)
def test_should_derive_exec_name_when_exec_line_is_odd(exec_line: str, expected: str) -> None:
    assert _entry(exec_line).exec_name == expected
