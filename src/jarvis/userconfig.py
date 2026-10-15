"""Set the user's name in config.toml without disturbing anything else.

There is no TOML writer in the project and the user's comments, ordering and line endings must
survive, so only the one `name` line is edited. A line editor can be fooled by unusual TOML (a
`name = ` line inside a multi-line string, `[ user ]`, an inline table), so every edit is checked:
the result must parse, hold the expected name, and have *exactly* the same data as before
everywhere else. If not, nothing is written and the user is told how to edit the file by hand.
"""

import contextlib
import json
import os
import re
import stat
import tempfile
import tomllib
import unicodedata
from pathlib import Path
from typing import Any

MAX_NAME_LEN = 40
# Control, lone surrogate, invisible/bidi formatting, and line/paragraph separators. The two
# joiners stay: some Persian and Indic names cannot be spelt without them.
_BAD_CATEGORIES = {"Cc", "Cs", "Cf", "Zl", "Zp"}
_JOINERS = {"‌", "‍"}


class InvalidNameError(ValueError):
    """Raised when a name is invalid or the config file cannot be safely edited."""


def clean_name(name: str) -> str:
    """Strip surrounding whitespace; raise InvalidNameError if the result is empty, longer than
    MAX_NAME_LEN, or has a control, surrogate, invisible-formatting or line-separator character."""
    stripped = name.strip()
    if not stripped:
        raise InvalidNameError("name must not be empty")
    if len(stripped) > MAX_NAME_LEN:
        raise InvalidNameError(f"name must be at most {MAX_NAME_LEN} characters")
    for ch in stripped:
        if unicodedata.category(ch) in _BAD_CATEGORIES and ch not in _JOINERS:
            raise InvalidNameError("name must not contain control or invisible characters")
    return stripped


_TABLE_HEADER_RE = re.compile(r"^\s*\[")
_CANT_EDIT = (
    "{file}'s [user] table is written in a form `jarvis setup` can't edit safely (for example a "
    'quoted key, an inline table or a multi-line string). Set `name = "..."` under a plain '
    "`[user]` header by hand. Nothing was changed."
)


def _find_section(lines: list[str], table: str) -> tuple[int, int] | None:
    """(header_index, end_index) of a plain `[table]` section, or None."""
    header = re.compile(rf"^\s*\[{table}\]\s*(#.*)?$")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _TABLE_HEADER_RE.match(lines[i])), None)
    return start, len(lines) if end is None else end


def _find_key(lines: list[str], section: tuple[int, int], key: str) -> int | None:
    pattern = re.compile(rf"^\s*{key}\s*=")
    return next((i for i in range(section[0] + 1, section[1]) if pattern.match(lines[i])), None)


def _split_lines(text: str) -> list[str]:
    """Split on LF only (TOML's newline), keeping each line's ending; "".join() restores text.

    str.splitlines() is not used: it also breaks on form feeds, U+2028 and friends,
    which are legal inside TOML comments and strings.
    """
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _line_ending(line: str) -> str:
    """The ending of one line: CRLF, LF, or "" for a final line without a newline."""
    if line.endswith("\r\n"):
        return "\r\n"
    return "\n" if line.endswith("\n") else ""


def _file_ending(text: str) -> str:
    """The ending the file uses (taken from its first line); LF when it has none."""
    first = _split_lines(text)[:1]
    return _line_ending(first[0]) or "\n" if first else "\n"


def _atomic_write(target: Path, content: str) -> None:
    """Replace `target` (a symlink is followed) with `content`: private temp file in the same
    folder, fsynced, given the old file's mode, then os.replace. Never leaves the temp file."""
    real = Path(os.path.realpath(target))
    real.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(real.stat().st_mode) if real.exists() else None
    fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=real.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _set_name_in_existing_section(
    lines: list[str], section: tuple[int, int], new_line: str, file_ending: str
) -> list[str]:
    """Set the name line in an existing [user] section."""
    name_idx = _find_key(lines, section, "name")
    if name_idx is not None:
        lines[name_idx] = new_line + _line_ending(lines[name_idx])
        return lines
    header_idx = section[0]
    header_ending = _line_ending(lines[header_idx])
    if header_ending:
        lines.insert(header_idx + 1, new_line + header_ending)
    else:  # the header is the last line and has no newline: give it one, keep EOF as it was
        lines[header_idx] += file_ending
        lines.append(new_line)
    return lines


def _append_user_section(lines: list[str], new_line: str, file_ending: str) -> list[str]:
    """Append a [user] section to the end of the file, in the file's own line ending."""
    if lines:
        if not lines[-1].endswith("\n"):
            lines[-1] += file_ending
        lines.append(file_ending)
    lines.append("[user]" + file_ending)
    lines.append(new_line + file_ending)
    return lines


def _edit(lines: list[str], name_line: str | None, file_ending: str) -> str:
    """The text with `name_line` set in [user], or the name line removed when it is None."""
    lines = list(lines)
    user = _find_section(lines, "user")
    if name_line is None:
        if user is not None and (idx := _find_key(lines, user, "name")) is not None:
            del lines[idx]
    elif user is not None:
        lines = _set_name_in_existing_section(lines, user, name_line, file_ending)
    else:
        lines = _append_user_section(lines, name_line, file_ending)
    return "".join(lines)


def _comparable(data: dict[str, Any]) -> dict[str, Any]:
    """The parsed data minus the one key we are allowed to change (`user.name`)."""
    out = dict(data)
    user = out.get("user")
    if isinstance(user, dict):
        rest = {key: value for key, value in user.items() if key != "name"}
        if rest:
            out["user"] = rest
        else:
            del out["user"]
    return out


def _verify(before: dict[str, Any], new_text: str, value: str | None) -> bool:
    """True when `new_text` parses, holds exactly `value` as user.name, and differs from the
    original in nothing else."""
    try:
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        return False
    user = after.get("user")
    name = user.get("name") if isinstance(user, dict) else None
    return name == value and _comparable(after) == _comparable(before)


def set_user_name(path: Path, name: str | None) -> None:
    """Set (or, with None, remove) `name` in the `[user]` table of the TOML file at `path`.

    Raises InvalidNameError (a ValueError) for a bad name or a file that cannot be edited
    safely; in that case the file is left exactly as it was."""
    value = None if name is None else clean_name(name)
    if not path.exists():
        if value is not None:
            _atomic_write(path, f"[user]\nname = {json.dumps(value, ensure_ascii=False)}\n")
        return

    try:
        original = Path(os.path.realpath(path)).read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidNameError(
            f"{path.name} is not valid UTF-8; open it in an editor and save it as UTF-8. "
            "Nothing was changed."
        ) from error
    try:
        before = tomllib.loads(original)
    except tomllib.TOMLDecodeError as error:
        raise InvalidNameError(
            f"{path.name} is not valid TOML ({error}); fix it first. Nothing was changed."
        ) from error

    user = before.get("user")
    if value is None and not (isinstance(user, dict) and "name" in user):
        return  # nothing to remove
    name_line = None if value is None else f"name = {json.dumps(value, ensure_ascii=False)}"
    new_text = _edit(_split_lines(original), name_line, _file_ending(original))
    if not _verify(before, new_text, value):
        raise InvalidNameError(_CANT_EDIT.format(file=path.name))
    if new_text != original:
        _atomic_write(path, new_text)
