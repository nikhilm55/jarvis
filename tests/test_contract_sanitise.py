import random
import time

import pytest

from jarvis.contract import sanitise_spoken

CASES = [
    ("Sent to Rahul Sharma.", "Sent to Rahul Sharma."),
    ("**Sent** to _Rahul_.", "Sent to Rahul."),
    ("## Status\nAll good.", "Status. All good."),
    ("- Opened Teams\n- Wrote the message", "Opened Teams. Wrote the message"),
    ("Read [the docs](https://example.com/a).", "Read the docs."),
    ("Details at https://example.com/x?y=1 and www.example.org.", "Details at and."),
    ("Done 🎉👍🏽 nice.", "Done nice."),
    ("Saved to /home/nikhil/notes.txt.", "Saved to a file."),
    ("Saved to ~/Documents/plan.md now.", "Saved to a file now."),
    (r"Saved to C:\Users\Nikhil O'Neil\My Docs\plan.txt.", "Saved to a file."),
    (r"Saved to C:\temp. Use this and/or that.", "Saved to a file. Use this and/or that."),
    ("Run `rm -rf build` first.", "Run first."),
    ("Here:\n```python\nprint('hi')\n```\nDone.", "Here: Done."),
    ("Use this and/or that on 10/07/2026.", "Use this and/or that on 10/07/2026."),
    ("राहुल को संदेश भेज दिया।", "राहुल को संदेश भेज दिया।"),
    ("Mr. Sharma replied. He is late. Call him?", "Mr. Sharma replied. He is late. Call him?"),
    ("**## Done**", "Done"),
    ("**1. Sent the message.**", "Sent the message."),
    ("_> quoted_", "quoted"),
    ("Done. **2. Next.**", "Done. Next."),
]
# Fragments that combine into markdown-ish text; a seeded generator keeps runs reproducible.
FRAGMENTS = [
    *("**", "*", "_", "__", "~~", "`", "## ", "> ", "- ", "1. ", "2) ", "---", "```"),
    *("\n", " ", "\n\n", "(", ")", ".", "!", ",", "🎉", "✓", "Done.", "Next?", "Mr."),
    *("[link](https://e.com/x)", "https://e.com/a.", "www.e.org", "/var/x.log", "~/notes.md"),
    *("C:\\My Docs\\a.txt", "word", "snake_case", "राहुल"),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_should_produce_speakable_text(text: str, expected: str) -> None:
    assert sanitise_spoken(text) == expected


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_should_be_idempotent(text: str, expected: str) -> None:
    assert sanitise_spoken(sanitise_spoken(text)) == sanitise_spoken(text)


def test_should_cap_at_two_sentences_when_long_is_not_allowed() -> None:
    assert sanitise_spoken("One. Two! Three? Four.") == "One. Two!"


def test_should_keep_a_closing_question_beyond_the_cap() -> None:
    assert sanitise_spoken("One. Two. Three. Ready?") == "One. Two. Ready?"


def test_should_keep_every_sentence_when_long_is_allowed() -> None:
    assert sanitise_spoken("One. Two! Three? Four.", allow_long=True) == "One. Two! Three? Four."


def test_should_return_empty_when_nothing_is_speakable() -> None:
    assert sanitise_spoken("https://example.com 🎉") == ""


@pytest.mark.parametrize("allow_long", [False, True])
def test_should_be_idempotent_on_generated_markdown(allow_long: bool) -> None:
    rng = random.Random(20261007)  # noqa: S311 — seeded for reproducible cases, not crypto
    for _ in range(2000):
        text = "".join(rng.choice(FRAGMENTS) for _ in range(rng.randint(1, 12)))
        once = sanitise_spoken(text, allow_long=allow_long)

        assert sanitise_spoken(once, allow_long=allow_long) == once, repr(text)
        assert not any(mark in once for mark in ("*", "`", "://", "\n")), repr(text)


@pytest.mark.parametrize("unit", ["The _foo and _bar names. ", "\n", "[a ", "~~a ", "*a ", "a."])
@pytest.mark.parametrize("allow_long", [False, True])
def test_should_stay_fast_when_input_is_huge_and_adversarial(unit: str, allow_long: bool) -> None:
    text = unit * (100_000 // len(unit))
    started = time.perf_counter()

    sanitise_spoken(text, allow_long=allow_long)

    assert time.perf_counter() - started < 0.5
