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


# Kokoro takes roughly 0.4 s plus 0.6 s per second of audio to synthesise, so the wait for the
# first sound grows with the length of the first chunk. A long first sentence is cut at its first
# clause boundary, never mid-clause: a cut with no mark can leave a gap while the rest is made.
_CLAUSE_END = (",", ";", ":", "\u2014", "\u2013")
_DASHES = ("-", "--")
_HEAD_MIN_WORDS = 2
_HEAD_MAX_WORDS = 6
_REST_MIN_WORDS = 3


def split_for_speech(text: str) -> list[str]:
    """Sentences to synthesise in order, with a long first one cut at its first clause.

    The cut falls after the first word that ends in a comma, semicolon, colon or dash within the
    first six words, provided the head has at least two words and the rest at least three.
    Without such a mark the sentence is left whole, and so is every later sentence.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []
    words = sentences[0].split()
    cut = _first_cut(words)
    if cut is None:
        return sentences
    return [" ".join(words[:cut]), " ".join(words[cut:]), *sentences[1:]]


def _first_cut(words: list[str]) -> int | None:
    """Where to split the words of a first sentence, or None to keep it whole."""
    last = min(_HEAD_MAX_WORDS, len(words) - _REST_MIN_WORDS)
    for count in range(_HEAD_MIN_WORDS, last + 1):
        word = words[count - 1]
        if word.endswith(_CLAUSE_END) or word in _DASHES:
            return count
    return None
