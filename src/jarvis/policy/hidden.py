"""Commands hidden inside a command line: `$(…)`, backticks and `<(…)` / `>(…)` (R94)."""


def _closing_paren(text: str, start: int) -> int:
    """Index of the `)` that closes the `(` at `start`, or -1. Quoted parentheses do not count."""
    depth, quote, i = 0, "", start
    while i < len(text):
        c = text[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            quote = "" if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _closing_backtick(text: str, start: int) -> int:
    i = start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            return i
        i += 1
    return -1


def inner_commands(cmd: str) -> list[str] | None:
    """The text of every command substitution in `cmd`, outermost first.

    `$(…)` and backticks run inside double quotes too; `<(…)` and `>(…)` only outside quotes;
    single quotes hide everything. None means one could not be read (an unclosed one).
    """
    found: list[str] = []
    quote, i = "", 0
    while i < len(cmd):
        c = cmd[i]
        if c == "\\" and quote != "'":
            i += 2
        elif quote == "'":
            quote = "" if c == "'" else quote
            i += 1
        elif c in "'\"":
            quote = "" if quote == c else (quote or c)
            i += 1
        elif c == "`" or cmd.startswith("$(", i) or (not quote and cmd[i : i + 2] in {"<(", ">("}):
            end = _closing_backtick(cmd, i + 1) if c == "`" else _closing_paren(cmd, i + 1)
            if end < 0:
                return None
            found.append(cmd[i + 1 : end] if c == "`" else cmd[i + 2 : end])
            i = end + 1
        else:
            i += 1
    return found
