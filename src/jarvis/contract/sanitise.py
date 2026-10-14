"""Deterministic `spoken` sanitiser (FRS FR-IO-02): plain, speakable, short."""

import re

_FENCED_CODE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"!?\[([^\[\]\n]*)\]\([^()\n]*\)")
_URL = re.compile(r"\b[a-zA-Z][\w+.\-]*://\S*[^\s.,;:!?)\]'\"]|\bwww\.\S*[^\s.,;:!?)\]'\"]")
_EMOJI = re.compile(r"[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]")
_RULE = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$", re.MULTILINE)
_LINE_MARKER = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+|\d+[.)][ \t]+)+", re.M)
_EMPHASIS = (
    re.compile(r"\*\*([^*\n]+)\*\*"),
    re.compile(r"~~([^~\n]+)~~"),
    re.compile(r"(?<!\w)__([^_\n]+)__(?!\w)"),
    re.compile(r"\*([^*\n]+)\*"),
    re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)"),
)
# Windows: segments may hold spaces, but not a filename-illegal character or a sentence end.
_WINDOWS_PATH = re.compile(
    r'\b[a-zA-Z]:[\\/](?:(?:(?![.!?,;]\s)[^\\/\n:*?"<>|])*[\\/])*(?:[^\s\\/]*[\w\-])?'
)
_POSIX_PATH = re.compile(r"(?<![\w/.~])(?:~|\.{1,2})?/[\w.\-/~]*[\w\-]")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_ABBREVIATIONS = ("mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "e.g.", "i.e.", "etc.")
_MAX_PASSES = 5  # stripping one layer can expose another ("**## Done**"); stop at a fixed point
_MAX_CHARS = 4_000  # bounds regex cost on huge output (§7.2); long content belongs in `display`


def sanitise_spoken(text: str, *, allow_long: bool = False) -> str:
    """Make `text` safe to say aloud. Returns "" when nothing speakable is left."""
    text = text[:_MAX_CHARS]
    for _ in range(_MAX_PASSES):
        cleaned = _clean(text)
        if cleaned == text:
            break
        text = cleaned
    return text if allow_long else _cap(text)


def _cap(text: str) -> str:
    """Two sentences, plus a closing question so a needed answer is never cut (FR-IO-02)."""
    sentences = _sentences(text)
    kept = sentences[:2]
    if len(sentences) > 2 and sentences[-1].endswith("?"):
        kept.append(sentences[-1])
    return " ".join(kept)


def _clean(text: str) -> str:
    text = _FENCED_CODE.sub("", text)
    text = _INLINE_CODE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _EMOJI.sub("", text)
    text = _RULE.sub("", text)
    text = _LINE_MARKER.sub("", text)
    for pattern in _EMPHASIS:
        text = pattern.sub(lambda m: _LINE_MARKER.sub("", m.group(1)), text)
    text = text.replace("*", "").replace("`", "")
    text = _WINDOWS_PATH.sub("a file", text)
    text = _POSIX_PATH.sub("a file", text)
    text = _join_lines(text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r" ([.,;:!?])", r"\1", text)
    return re.sub(r"^[\s.,;:!?\-]+", "", text).strip()


def _join_lines(text: str) -> str:
    """Turn line breaks (list items, headings) into sentence breaks so speech keeps them apart."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ended = [line if line[-1] in ".!?…:;," else f"{line}." for line in lines[:-1]]
    return " ".join([*ended, *lines[-1:]])


def _sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for piece in _SENTENCE_END.split(text):
        if sentences and sentences[-1].split()[-1].lower() in _ABBREVIATIONS:
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return sentences
