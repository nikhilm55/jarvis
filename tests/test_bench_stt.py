"""Tests for the word error rate functions in scripts/bench_stt.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bench_stt", ROOT / "scripts" / "bench_stt.py")
assert spec and spec.loader
bench_stt = importlib.util.module_from_spec(spec)
sys.modules["bench_stt"] = bench_stt
spec.loader.exec_module(bench_stt)


def test_should_return_lowercased_words_without_punctuation_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("Jarvis, open Teams.")
    assert result == ["jarvis", "open", "teams"]


def test_should_keep_apostrophes_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("I'll be 10 minutes")
    assert result == ["i'll", "be", "ten", "minutes"]


def test_should_convert_percent_sign_to_word_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("40%")
    assert result == ["forty", "percent"]


def test_should_convert_percent_word_to_word_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("40 percent")
    assert result == ["forty", "percent"]


def test_should_return_empty_list_when_normalise_words_called_with_empty_string() -> None:
    result = bench_stt.normalise_words("")
    assert result == []


def test_should_convert_zero_to_zero_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("0")
    assert result == ["zero"]


def test_should_convert_thirteen_to_thirteen_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("13")
    assert result == ["thirteen"]


def test_should_convert_twenty_to_twenty_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("20")
    assert result == ["twenty"]


def test_should_convert_twenty_one_to_two_tokens_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("21")
    assert result == ["twenty", "one"]


def test_should_convert_ninety_nine_to_two_tokens_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("99")
    assert result == ["ninety", "nine"]


def test_should_keep_hundred_unchanged_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("100")
    assert result == ["100"]


def test_should_keep_leading_zeros_unchanged_when_normalise_words_called() -> None:
    result = bench_stt.normalise_words("007")
    assert result == ["007"]


def test_should_return_zero_when_word_errors_called_with_identical_lists() -> None:
    result = bench_stt.word_errors(["open", "the", "door"], ["open", "the", "door"])
    assert result == 0


def test_should_return_one_when_word_errors_called_with_one_substitution() -> None:
    result = bench_stt.word_errors(["open", "the", "door"], ["open", "the", "window"])
    assert result == 1


def test_should_return_one_when_word_errors_called_with_one_insertion() -> None:
    result = bench_stt.word_errors(["open", "door"], ["open", "the", "door"])
    assert result == 1


def test_should_return_one_when_word_errors_called_with_one_deletion() -> None:
    result = bench_stt.word_errors(["open", "the", "door"], ["open", "door"])
    assert result == 1


def test_should_return_length_of_other_when_word_errors_called_with_empty_list() -> None:
    result = bench_stt.word_errors([], ["a", "b", "c"])
    assert result == 3
    result2 = bench_stt.word_errors(["a", "b"], [])
    assert result2 == 2


def test_should_compute_corpus_wer_when_wer_called() -> None:
    refs = ["open the door"]
    hyps = ["open door"]
    result = bench_stt.wer(refs, hyps)
    assert result == pytest.approx(1 / 3)


def test_should_compute_corpus_wer_for_multiple_pairs_when_wer_called() -> None:
    refs = ["a b", "c d"]
    hyps = ["a b", "c x"]
    result = bench_stt.wer(refs, hyps)
    assert result == pytest.approx(0.25)


def test_should_ignore_casing_punctuation_and_digit_word_differences_when_wer_called() -> None:
    refs = ["Ten minutes."]
    hyps = ["10 minutes"]
    result = bench_stt.wer(refs, hyps)
    assert result == 0.0


def test_should_raise_value_error_when_wer_called_with_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        bench_stt.wer(["a", "b"], ["c"])
