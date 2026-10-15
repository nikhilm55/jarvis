"""Tests for jarvis.userconfig: edit one `name` line, touch nothing else."""

import os
import sys
import tomllib
from pathlib import Path

import pytest

from jarvis import userconfig
from jarvis.userconfig import InvalidNameError, clean_name, set_user_name

# A realistic file: comments, a table before and one after [user].
LF_FILE = (
    '# top comment\n[brain]\nmodel = "sonnet"  # keep me\n\n'
    '[user]\n# who I am\nname = "Old"\nlanguage = "en"\n\n[tts]\nvoice = "bm_george"\n'
)


def _put(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("utf-8"))
    return path


def _get(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def test_should_create_new_file_and_parent_dirs_with_just_the_user_table(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "config.toml"
    set_user_name(path, "Alice")
    assert _get(path) == '[user]\nname = "Alice"\n'
    assert tomllib.loads(_get(path)) == {"user": {"name": "Alice"}}


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_should_replace_name_line_leaving_every_other_byte_identical(
    tmp_path: Path, eol: str
) -> None:
    original = LF_FILE.replace("\n", eol)
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, "New")
    assert _get(path) == original.replace('name = "Old"', 'name = "New"')
    assert tomllib.loads(_get(path))["user"]["name"] == "New"


def test_should_insert_name_right_after_user_header_without_name(tmp_path: Path) -> None:
    path = _put(tmp_path / "config.toml", "[user]\r\n# comment\r\n\r\n[other]\r\nx = 1\r\n")
    set_user_name(path, "Bob")
    assert _get(path) == '[user]\r\nname = "Bob"\r\n# comment\r\n\r\n[other]\r\nx = 1\r\n'


def test_should_insert_name_when_user_header_is_the_last_line_without_newline(
    tmp_path: Path,
) -> None:
    path = _put(tmp_path / "config.toml", "[brain]\nx = 1\n[user]")
    set_user_name(path, "Bob")
    assert _get(path) == '[brain]\nx = 1\n[user]\nname = "Bob"'


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_should_append_user_table_in_the_files_own_line_ending(tmp_path: Path, eol: str) -> None:
    original = f"[other]{eol}x = 1{eol}"
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, "Carol")
    assert _get(path) == f'{original}{eol}[user]{eol}name = "Carol"{eol}'


def test_should_append_user_table_when_file_does_not_end_with_newline(tmp_path: Path) -> None:
    path = _put(tmp_path / "config.toml", "[other]\nx = 1")
    set_user_name(path, "Dave")
    assert _get(path) == '[other]\nx = 1\n\n[user]\nname = "Dave"\n'


def test_should_write_user_table_into_an_empty_existing_file(tmp_path: Path) -> None:
    path = _put(tmp_path / "config.toml", "")
    set_user_name(path, "Dave")
    assert _get(path) == '[user]\nname = "Dave"\n'


@pytest.mark.parametrize("has_user_table", [False, True])
def test_should_not_touch_name_key_of_another_table(tmp_path: Path, has_user_table: bool) -> None:
    other = '[other]\nname = "x"\n'
    original = other + ('\n[user]\nname = "Old"\n' if has_user_table else "")
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, "Eve")
    assert _get(path).startswith(other)
    data = tomllib.loads(_get(path))
    assert data["other"]["name"] == "x"
    assert data["user"]["name"] == "Eve"


def test_should_not_treat_unicode_line_separators_in_a_comment_as_lines(tmp_path: Path) -> None:
    ls = chr(0x2028)  # a legal character inside a TOML comment
    original = f'[user]\n# a{ls}[fake]\nname = "Old"\n'
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, "New")
    assert _get(path) == original.replace("Old", "New")


def test_should_remove_only_the_name_line(tmp_path: Path) -> None:
    original = '[other]\nname = "keep"\n\n[user]\nname = "Old"\nlanguage = "en"\n'
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, None)
    assert _get(path) == '[other]\nname = "keep"\n\n[user]\nlanguage = "en"\n'


def test_should_leave_an_empty_user_header_after_removing_the_only_key(tmp_path: Path) -> None:
    path = _put(tmp_path / "config.toml", '[user]\r\nname = "Old"\r\n')
    set_user_name(path, None)
    assert _get(path) == "[user]\r\n"


@pytest.mark.parametrize("original", ["[user]\nlanguage = 1\n", "[brain]\nx = 1\n", ""])
def test_should_be_noop_when_removing_an_absent_name(tmp_path: Path, original: str) -> None:
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, None)
    assert _get(path) == original


def test_should_be_noop_and_create_nothing_when_removing_from_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "config.toml"
    set_user_name(path, None)
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("Nikhil", "Nikhil"),
        ('O"Brien', 'O"Brien'),
        ("back\\slash", "back\\slash"),
        ("José", "José"),
        ("नमस्ते", "नमस्ते"),
        ("  Ana  ", "Ana"),
        ("a" * 40, "a" * 40),
    ],
)
def test_should_round_trip_tricky_names_through_tomllib(
    tmp_path: Path, raw: str, stored: str
) -> None:
    fresh = tmp_path / "fresh.toml"
    set_user_name(fresh, raw)
    assert tomllib.loads(_get(fresh))["user"]["name"] == stored
    replaced = _put(tmp_path / "replaced.toml", '[user]\nname = "Old"\n')
    set_user_name(replaced, raw)
    assert tomllib.loads(_get(replaced))["user"]["name"] == stored


# control, lone surrogate (argv can carry one), bidi/zero-width, and line separators
BAD_NAMES = ["", "   ", "a" * 41, "a\nb", "a\tb", "a\x7fb", "a\rb", "a\udcffb", "a\u202eb"]
BAD_NAMES += ["a\u200bb", "a\u2028b", "a\u2029b", "\ufeffAna"]


@pytest.mark.parametrize("bad", BAD_NAMES)
def test_should_reject_bad_names_without_creating_or_changing_the_file(
    tmp_path: Path, bad: str
) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(InvalidNameError):
        set_user_name(missing, bad)
    assert not missing.exists()

    existing = _put(tmp_path / "config.toml", LF_FILE)
    with pytest.raises(InvalidNameError):
        set_user_name(existing, bad)
    assert _get(existing) == LF_FILE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml"]  # no temp file left


def test_should_strip_and_accept_a_name_of_exactly_the_maximum_length() -> None:
    assert clean_name("  " + "é" * 40 + "\n") == "é" * 40
    with pytest.raises(InvalidNameError):
        clean_name("é" * 41)


def test_should_refuse_to_edit_a_file_that_is_not_valid_toml(tmp_path: Path) -> None:
    original = "this is not = valid toml"
    path = _put(tmp_path / "config.toml", original)
    with pytest.raises(InvalidNameError):
        set_user_name(path, "Alice")
    with pytest.raises(InvalidNameError):
        set_user_name(path, None)
    assert _get(path) == original


def test_should_restore_the_original_when_the_edit_would_corrupt_the_file(tmp_path: Path) -> None:
    original = '[user]\nname = """\nmulti\nline"""\n'  # valid TOML, but not a one-line value
    path = _put(tmp_path / "config.toml", original)
    with pytest.raises(InvalidNameError):
        set_user_name(path, "Alice")
    assert _get(path) == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml"]


UNEDITABLE = [
    '[ user ]\nname = "Old"\n',
    '["user"]\nname = "Old"\n',
    '[user]\n"name" = "Old"\n',
    'user = { name = "Old" }\n',
    'user.name = "Old"\n',
    '[user]\nnote = """\nname = x\nkeep\n"""\nname = "Old"\n',  # a "name =" line inside a string
]


@pytest.mark.parametrize("original", UNEDITABLE)
@pytest.mark.parametrize("new", ["Alice", None])
def test_should_refuse_with_a_remedy_when_user_is_written_in_a_form_it_cannot_edit(
    tmp_path: Path, original: str, new: str | None
) -> None:
    path = _put(tmp_path / "config.toml", original)
    with pytest.raises(InvalidNameError, match=r"can't edit safely.*plain `\[user\]` header"):
        set_user_name(path, new)
    assert _get(path) == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml"]


def test_should_not_delete_a_name_looking_line_inside_a_multiline_string(tmp_path: Path) -> None:
    original = '[user]\nnote = """\nname = x\nkeep\n"""\n'
    path = _put(tmp_path / "config.toml", original)
    set_user_name(path, None)  # there is no name to remove: nothing to do, nothing lost
    assert _get(path) == original
    with pytest.raises(InvalidNameError):  # setting would overwrite the line in the string
        set_user_name(path, "Alice")
    assert _get(path) == original


def test_should_refuse_a_file_that_is_not_utf8_with_a_remedy(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'[user]\nname = "\xff"\n')
    with pytest.raises(InvalidNameError, match=r"not valid UTF-8.*save"):
        set_user_name(path, "Alice")
    assert path.read_bytes() == b'[user]\nname = "\xff"\n'


def test_should_leave_no_temp_file_and_keep_the_original_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _put(tmp_path / "config.toml", LF_FILE)

    def boom(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        set_user_name(path, "New")
    assert _get(path) == LF_FILE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml"]


def test_should_not_use_or_clobber_a_fixed_temp_file_name(tmp_path: Path) -> None:
    path = _put(tmp_path / "config.toml", LF_FILE)
    bystander = _put(tmp_path / "config.toml.tmp", "someone else's file")
    set_user_name(path, "New")
    assert _get(bystander) == "someone else's file"
    assert _get(path) == LF_FILE.replace("Old", "New")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml", "config.toml.tmp"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_should_keep_the_file_mode_of_an_existing_config(tmp_path: Path) -> None:
    path = _put(tmp_path / "config.toml", LF_FILE)
    path.chmod(0o600)
    set_user_name(path, "New")
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o640)
    set_user_name(path, None)
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_should_update_the_target_of_a_symlinked_config_and_keep_the_link(tmp_path: Path) -> None:
    (tmp_path / "dotfiles").mkdir()
    target = _put(tmp_path / "dotfiles" / "config.toml", LF_FILE)
    link = tmp_path / "config.toml"
    link.symlink_to(target)
    set_user_name(link, "New")
    assert link.is_symlink()
    assert _get(target) == LF_FILE.replace("Old", "New")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml", "dotfiles"]
    assert sorted(p.name for p in target.parent.iterdir()) == ["config.toml"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_should_create_through_a_dangling_symlink(tmp_path: Path) -> None:
    link = tmp_path / "config.toml"
    link.symlink_to(tmp_path / "elsewhere" / "real.toml")
    set_user_name(link, "New")
    assert link.is_symlink()
    assert _get(tmp_path / "elsewhere" / "real.toml") == '[user]\nname = "New"\n'


def test_should_accept_the_joiners_that_some_names_need() -> None:
    name = "नमस्ते" + chr(0x200C) + "जी"  # ZWNJ is part of how some Indic and Persian names are spelt
    assert clean_name(name) == name


LEGACY = '[brain]\nmodel = "opus"\naddress_as = "Boss"  # old\n\n[tts]\nvoice = "x"\n'


def test_should_remove_a_leftover_brain_address_as_line_when_setting_the_name(
    tmp_path: Path,
) -> None:
    path = _put(tmp_path / "config.toml", LEGACY)
    note = set_user_name(path, "Nik")
    assert _get(path) == '[brain]\nmodel = "opus"\n\n[tts]\nvoice = "x"\n\n[user]\nname = "Nik"\n'
    assert note == 'Removed the old brain.address_as setting ("Boss") from config.toml.'


def test_should_leave_address_as_of_another_table_and_say_nothing(tmp_path: Path) -> None:
    original = '[other]\naddress_as = "x"\n'
    path = _put(tmp_path / "config.toml", original)
    assert set_user_name(path, "Nik") is None
    assert _get(path) == original + '\n[user]\nname = "Nik"\n'


def test_should_set_the_name_but_keep_address_as_and_say_so_when_removal_is_not_safe(
    tmp_path: Path,
) -> None:
    original = '[brain]\naddress_as = """\nBoss\n"""\n'  # not a one-line value
    path = _put(tmp_path / "config.toml", original)
    note = set_user_name(path, "Nik")
    assert _get(path) == original + '\n[user]\nname = "Nik"\n'
    assert note is not None
    assert "delete that line" in note


def test_should_keep_address_as_when_clearing_the_name(tmp_path: Path) -> None:
    original = LEGACY + '\n[user]\nname = "Old"\n'
    path = _put(tmp_path / "config.toml", original)
    assert set_user_name(path, None) is None
    assert _get(path) == original.replace('name = "Old"\n', "")


NOT_REMOVABLE = ['brain = { address_as = "Boss" }\n', '[brain]\n"address_as" = "Boss"\n']


@pytest.mark.parametrize("original", NOT_REMOVABLE)
def test_should_not_claim_to_remove_address_as_in_a_form_it_cannot_delete(
    tmp_path: Path, original: str
) -> None:
    path = _put(tmp_path / "config.toml", original)
    note = set_user_name(path, "Nik")
    assert _get(path) == original + '\n[user]\nname = "Nik"\n'  # name set, nothing else touched
    assert note is not None
    assert "Removed" not in note
    assert "delete that line" in note


def test_should_not_claim_removal_when_the_edit_deleted_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_edit = userconfig._edit  # mutation: an editor that deletes nothing

    def never_drops(lines: list[str], name_line: str | None, ending: str, _drop: bool) -> str:
        return real_edit(lines, name_line, ending, False)

    monkeypatch.setattr(userconfig, "_edit", never_drops)
    path = _put(tmp_path / "config.toml", LEGACY)
    note = set_user_name(path, "Nik")
    assert _get(path) == LEGACY + '\n[user]\nname = "Nik"\n'
    assert note is not None
    assert "Removed" not in note


def test_should_fsync_the_temp_file_before_it_replaces_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        calls.append(("fsync", os.fstat(fd).st_ino))
        real_fsync(fd)

    def replace(src: str | Path, dst: str | Path) -> None:
        calls.append(("replace", os.stat(src).st_ino))
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    path = _put(tmp_path / "config.toml", LF_FILE)
    set_user_name(path, "New")
    assert [name for name, _ in calls] == ["fsync", "replace"]
    assert calls[0][1] == calls[1][1]  # the file that was fsynced is the one that was moved
    assert _get(path) == LF_FILE.replace("Old", "New")
