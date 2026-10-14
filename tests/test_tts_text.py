"""Tests for jarvis.tts.text.split_sentences."""

from __future__ import annotations

import pytest

from jarvis.tts.text import split_sentences


def test_should_return_single_sentence_when_text_has_terminal_punctuation() -> None:
    # Arrange
    text = "Hello there."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Hello there."]


def test_should_return_multiple_sentences_when_text_has_several_sentences() -> None:
    # Arrange
    text = "First one. Second one! Third one?"
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["First one.", "Second one!", "Third one?"]


def test_should_return_single_sentence_when_text_has_no_terminal_punctuation() -> None:
    # Arrange
    text = "This has no ending"
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["This has no ending"]


def test_should_return_empty_list_when_input_is_empty() -> None:
    # Arrange
    text = ""
    # Act
    result = split_sentences(text)
    # Assert
    assert result == []


def test_should_return_empty_list_when_input_is_whitespace_only() -> None:
    # Arrange
    text = "   \t  \n  "
    # Act
    result = split_sentences(text)
    # Assert
    assert result == []


def test_should_split_on_newlines_when_text_contains_newlines() -> None:
    # Arrange
    text = "Line one.\nLine two.\nLine three."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Line one.", "Line two.", "Line three."]


def test_should_not_split_inside_decimals_when_number_contains_dot() -> None:
    # Arrange
    text = "The temperature is 3.5 degrees today."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["The temperature is 3.5 degrees today."]


def test_should_not_split_inside_version_numbers_when_multiple_dots_present() -> None:
    # Arrange
    text = "Please install version 2.0.1 of the package."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Please install version 2.0.1 of the package."]


@pytest.mark.parametrize(
    "abbreviation",
    ["Mr.", "Mrs.", "Ms.", "Dr.", "St.", "vs.", "etc.", "i.e.", "e.g."],
    ids=["mr", "mrs", "ms", "dr", "st", "vs", "etc", "ie", "eg"],
)
def test_should_not_split_after_common_abbreviations(
    abbreviation: str,
) -> None:
    # Arrange
    text = f"Hello {abbreviation} Smith is here."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == [f"Hello {abbreviation} Smith is here."]


def test_should_not_split_after_single_initial_when_initial_followed_by_space() -> None:
    # Arrange
    text = "J. Smith was here."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["J. Smith was here."]


def test_should_keep_multiple_punctuation_attached_when_question_and_exclamation() -> None:
    # Arrange
    text = "Really?!"
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Really?!"]


def test_should_split_after_ellipsis_character_when_followed_by_whitespace() -> None:
    # Arrange
    text = "Wait a moment… Then continue."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Wait a moment…", "Then continue."]


def test_should_keep_quotes_attached_when_period_followed_by_closing_quote() -> None:
    # Arrange
    text = 'He said "Hello." Then he left.'
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ['He said "Hello."', "Then he left."]


def test_should_split_after_hindi_danda_when_followed_by_whitespace() -> None:
    # Arrange
    text = "नमस्ते। यह एक वाक्य है।"
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["नमस्ते।", "यह एक वाक्य है।"]


def test_should_collapse_whitespace_runs_to_single_spaces_inside_sentence() -> None:
    # Arrange
    text = "Hello    world.   Next   sentence."
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Hello world.", "Next sentence."]


def test_should_handle_realistic_assistant_reply_with_three_sentences() -> None:
    # Arrange
    text = (
        "Good morning! I have checked the weather for you. "
        "It is currently 22 degrees and partly cloudy. "
        "Would you like me to set a reminder for later?"
    )
    # Act
    result = split_sentences(text)
    # Assert
    assert result == [
        "Good morning!",
        "I have checked the weather for you.",
        "It is currently 22 degrees and partly cloudy.",
        "Would you like me to set a reminder for later?",
    ]


def test_should_handle_unicode_accents_when_text_contains_accented_characters() -> None:
    # Arrange
    text = "Café au lait. Crème brûlée. Voilà!"
    # Act
    result = split_sentences(text)
    # Assert
    assert result == ["Café au lait.", "Crème brûlée.", "Voilà!"]
