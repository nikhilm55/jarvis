"""Set the user's name in config.toml without disturbing anything else."""

import json
import os
import re
import tomllib
import unicodedata
from pathlib import Path

MAX_NAME_LEN = 40


class InvalidNameError(ValueError):
    """Raised when a name is invalid or the config file cannot be safely edited."""


def clean_name(name: str) -> str:
    """Strip surrounding whitespace; raise InvalidNameError if the result is empty,
    longer than MAX_NAME_LEN, or contains any control character (unicodedata category "Cc",
    which includes newline and tab)."""
    stripped = name.strip()
    if not stripped:
        raise InvalidNameError("name must not be empty")
    if len(stripped) > MAX_NAME_LEN:
        raise InvalidNameError(f"name must be at most {MAX_NAME_LEN} characters")
    for ch in stripped:
        if unicodedata.category(ch) == "Cc":
            raise InvalidNameError("name must not contain control characters")
    return stripped


_USER_HEADER_RE = re.compile(r"^\s*\[user\]\s*(#.*)?$")
_TABLE_HEADER_RE = re.compile(r"^\s*\[")
_NAME_LINE_RE = re.compile(r"^\s*name\s*=")


def _find_user_section(lines: list[str]) -> tuple[int, int] | None:
    """Return (header_index, end_index) of the [user] section, or None."""
    header_idx = None
    for i, line in enumerate(lines):
        if _USER_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return None
    end_idx = len(lines)
    for i in range(header_idx + 1, len(lines)):
        if _TABLE_HEADER_RE.match(lines[i]):
            end_idx = i
            break
    return (header_idx, end_idx)


def _find_name_line(lines: list[str], start: int, end: int) -> int | None:
    """Return the index of the name line within [start, end), or None."""
    for i in range(start, end):
        if _NAME_LINE_RE.match(lines[i]):
            return i
    return None


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


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a sibling temp file, then os.replace over path."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    os.replace(tmp, path)


def _read_text_preserve(path: Path) -> str:
    """Read file text preserving line endings."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _handle_missing_file(path: Path, name: str | None, value: str | None) -> None:
    """Handle the case where the file does not exist."""
    if name is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"[user]\nname = {json.dumps(value, ensure_ascii=False)}\n"
    _atomic_write(path, content)


def _remove_name_line(lines: list[str], section: tuple[int, int]) -> list[str]:
    """Remove the name line from the user section."""
    header_idx, end_idx = section
    name_idx = _find_name_line(lines, header_idx + 1, end_idx)
    if name_idx is not None:
        del lines[name_idx]
    return lines


def _set_name_in_existing_section(
    lines: list[str], section: tuple[int, int], new_line: str, file_ending: str
) -> list[str]:
    """Set the name line in an existing [user] section."""
    header_idx, end_idx = section
    name_idx = _find_name_line(lines, header_idx + 1, end_idx)
    if name_idx is not None:
        lines[name_idx] = new_line + _line_ending(lines[name_idx])
        return lines
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


def _verify_result(new_text: str, name: str | None, value: str | None) -> None:
    """Verify the result parses and has the expected name."""
    try:
        data = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as error:
        raise InvalidNameError(f"result is not valid TOML: {error}") from error

    user_data = data.get("user", {})
    if name is not None:
        if user_data.get("name") != value:
            raise InvalidNameError("result does not contain the expected name")
    elif "name" in user_data:
        raise InvalidNameError("result still contains a name after removal")


def set_user_name(path: Path, name: str | None) -> None:
    """Set (or, with None, remove) `name` in the `[user]` table of the TOML file at `path`."""
    value = clean_name(name) if name is not None else None

    if not path.exists():
        _handle_missing_file(path, name, value)
        return

    original_text = _read_text_preserve(path)

    try:
        tomllib.loads(original_text)
    except tomllib.TOMLDecodeError as error:
        raise InvalidNameError(f"original file is not valid TOML: {error}") from error

    lines = _split_lines(original_text)
    section = _find_user_section(lines)

    if name is None:
        if section is None:
            return
        lines = _remove_name_line(lines, section)
        new_text = "".join(lines)
    else:
        new_line = f"name = {json.dumps(value, ensure_ascii=False)}"
        file_ending = _file_ending(original_text)
        if section is not None:
            lines = _set_name_in_existing_section(lines, section, new_line, file_ending)
        else:
            lines = _append_user_section(lines, new_line, file_ending)
        new_text = "".join(lines)

    _verify_result(new_text, name, value)
    _atomic_write(path, new_text)
