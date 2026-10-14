"""Split text into sentences for TTS."""

import re

_SENT_END = re.compile(r"[.!?…।][\"'\")\]\u201d\u2019]*$")
_ABBREV = re.compile(
    r"^(?:Mr|Mrs|Ms|Dr|St|vs|etc|i\.e|e\.g)\.$",
    re.IGNORECASE,
)
_INITIAL = re.compile(r"^[A-Z]\.$")


def _is_sentence_end(word: str) -> bool:
    if not _SENT_END.search(word):
        return False
    return not (_ABBREV.match(word) or _INITIAL.match(word))


def _split_line(line: str) -> list[str]:
    words = line.split()
    if not words:
        return []
    sentences: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if _is_sentence_end(word):
            piece = " ".join(current)
            if piece:
                sentences.append(piece)
            current = []
    if current:
        piece = " ".join(current)
        if piece:
            sentences.append(piece)
    return sentences


def split_sentences(text: str) -> list[str]:
    lines = text.split("\n")
    result: list[str] = []
    for line in lines:
        result.extend(_split_line(line))
    return result
