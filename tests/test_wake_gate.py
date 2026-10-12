import dataclasses

import pytest

from jarvis.wake.gate import GateResult, gate, levenshtein


def test_should_return_zero_when_both_strings_are_empty() -> None:
    assert levenshtein("", "") == 0


def test_should_return_three_when_first_string_is_abc_and_second_is_empty() -> None:
    assert levenshtein("abc", "") == 3


def test_should_return_three_when_first_string_is_empty_and_second_is_abc() -> None:
    assert levenshtein("", "abc") == 3


def test_should_return_zero_when_both_strings_are_identical_jarvis() -> None:
    assert levenshtein("jarvis", "jarvis") == 0


def test_should_return_one_when_first_is_jarvis_and_second_is_darvis() -> None:
    assert levenshtein("jarvis", "darvis") == 1


def test_should_return_one_when_first_is_jarvis_and_second_is_jarvs() -> None:
    assert levenshtein("jarvis", "jarvs") == 1


def test_should_return_three_when_first_is_kitten_and_second_is_sitting() -> None:
    assert levenshtein("kitten", "sitting") == 3


def test_should_return_three_when_first_is_travis_and_second_is_jarvis() -> None:
    assert levenshtein("travis", "jarvis") == 3


@pytest.mark.parametrize(
    ("transcript", "expected_command"),
    (
        ("Jarvis, open Teams", "open Teams"),
        ("Jervis open Teams", "open Teams"),
        ("jarvis's open Teams", "open Teams"),
        ("JARVIS open Teams", "open Teams"),
        ("Jarvas open Teams", "open Teams"),
        ("Javis open Teams", "open Teams"),
        ("Darvis open Teams", "open Teams"),
        ("Garvis open Teams", "open Teams"),
        ("Jarvus open Teams", "open Teams"),
    ),
)
def test_should_accept_when_transcript_starts_with_variant(
    transcript: str,
    expected_command: str,
) -> None:
    result = gate(transcript)
    assert result.accepted is True
    assert result.command == expected_command


@pytest.mark.parametrize(
    ("transcript", "expected_first_word"),
    (
        ("Travis open Teams", "travis"),
        ("Service is down", "service"),
        ("Nervous about it", "nervous"),
        ("Harvey open Teams", "harvey"),
        ("Marvin, open Teams", "marvin"),
        ("Harvest the data", "harvest"),
        ("I told Jarvis to open Teams", "i"),
        ("Hey Jarvis open Teams", "hey"),
        ("Please ask Jarvis", "please"),
        ("", ""),
        ("   ", ""),
        ("...", ""),
        ("?!", ""),
        ("Hello there", "hello"),
        ("Open Teams", "open"),
    ),
)
def test_should_reject_when_transcript_does_not_start_with_wake_word(
    transcript: str,
    expected_first_word: str,
) -> None:
    result = gate(transcript)
    assert result.accepted is False
    assert result.command == ""
    assert result.first_word == expected_first_word


def test_should_report_first_word_as_travis_when_transcript_starts_with_travis() -> None:
    assert gate("Travis open Teams").first_word == "travis"


def test_should_report_first_word_as_empty_when_transcript_is_empty() -> None:
    assert gate("").first_word == ""


def test_should_report_first_word_as_jarvis_s_when_transcript_starts_with_jarvis_s() -> None:
    assert gate("Jarvis's turn").first_word == "jarvis's"


@pytest.mark.parametrize(
    ("transcript", "expected_command"),
    (
        ("Jarvis, open Teams", "open Teams"),
        ("Jarvis open Teams", "open Teams"),
        ("Jarvis, um, open Teams", "open Teams"),
        ("Jarvis, uh okay so Open Teams.", "Open Teams."),
        ("Jarvis... Mute the sound!", "Mute the sound!"),
        ("Jarvis, open Teams.   ", "open Teams."),
        ("Jarvis.", ""),
        ("Jarvis", ""),
        ("Jarvis, um", ""),
        ("Jarvis, soon open Teams", "soon open Teams"),
        ("Jarvis,open Teams", "open Teams"),
        ("Jarvis, Open TEAMS and Slack", "Open TEAMS and Slack"),
    ),
)
def test_should_extract_command_when_transcript_is_accepted(
    transcript: str,
    expected_command: str,
) -> None:
    result = gate(transcript)
    assert result.accepted is True
    assert result.command == expected_command


def test_should_return_empty_command_when_transcript_is_rejected() -> None:
    result = gate("Travis open Teams")
    assert result.accepted is False
    assert result.command == ""


def test_should_be_immutable_when_gate_result_is_built() -> None:
    result = GateResult(accepted=True, command="x", first_word="jarvis")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.command = "y"  # type: ignore[misc]


def test_should_normalise_curly_apostrophe_when_first_word_is_possessive() -> None:
    result = gate(f"Jarvis{chr(0x2019)}s turn")

    assert (result.accepted, result.first_word, result.command) == (True, "jarvis's", "turn")


def test_should_keep_hyphenated_word_when_it_merely_starts_with_a_filler() -> None:
    assert gate("Jarvis, Okay-ish plan").command == "Okay-ish plan"
