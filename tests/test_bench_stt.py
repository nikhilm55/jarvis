"""Tests for scripts/bench_stt.py: word error rate, the model recommendation and the loaders."""

import importlib.util
import json
import sys
import wave
from pathlib import Path

import numpy as np
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


def _row(model: str, p50_ms: float, p50_3s_ms: float | None) -> object:
    return bench_stt.Row(model, 10, p50_ms, p50_ms * 1.3, 1.0, {"m0a": 0.0}, p50_3s_ms)


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([("tiny", 900, 700), ("base", 1200, 790), ("small", 2000, 1600)], "base"),  # 3 s p50 rules
        ([("tiny", 700, None), ("base", 900, None)], "tiny"),  # no 3 s clips: overall p50
        ([("tiny", 900, 850)], None),
        ([("tiny", 900, 0.0)], "tiny"),  # a 0 ms p50 is a value, not a missing one
    ],
)
def test_should_recommend_the_last_model_within_the_limit(
    rows: list[tuple[str, float, float | None]], expected: str | None
) -> None:
    built = [bench_stt.Row(m, 10, p50, p50 * 1.3, 1.0, {"m0a": 0.0}, p3) for m, p50, p3 in rows]
    assert bench_stt.recommend(built, 800.0) == expected


def _write_wav(path: Path, samples: int, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setparams((1, 2, rate, samples, "NONE", "not compressed"))
        w.writeframes(np.zeros(samples, dtype="<i2").tobytes())


def test_should_load_acceptance_fixtures_with_their_reference_text(tmp_path: Path) -> None:
    _write_wav(tmp_path / "b-clip.wav", 1600)
    _write_wav(tmp_path / "a-clip.wav", 3200)
    manifest = {"b-clip": {"text": "Jarvis, volume up."}, "a-clip": {"text": "Open Calculator."}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    got = [(c.name, c.text, len(c.pcm)) for c in bench_stt.load_acceptance(tmp_path)]
    assert got == [("a-clip", "Open Calculator.", 3200), ("b-clip", "Jarvis, volume up.", 1600)]


def _m0a_dir(tmp_path: Path, categories: list[str]) -> Path:
    rows = ["clip,category,text"]
    for index, category in enumerate(categories):
        name = f"{category}-{index:05d}"
        (tmp_path / category).mkdir(exist_ok=True)
        _write_wav(tmp_path / category / f"{name}.wav", 1600)
        rows.append(f'{name},{category},"Jarvis, text {index}"')
    (tmp_path / "manifest.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return tmp_path


def test_should_load_only_jarvis_command_clips_up_to_the_count(tmp_path: Path) -> None:
    kinds = ["jarvis_alone", "jarvis_command", "jarvis_command", "jarvis_command"]
    clips = bench_stt.load_m0a(_m0a_dir(tmp_path, kinds), 2)
    assert [(c.corpus, c.name, c.text) for c in clips] == [
        ("m0a", "jarvis_command-00001", "Jarvis, text 1"),
        ("m0a", "jarvis_command-00002", "Jarvis, text 2"),
    ]


def test_should_stop_when_a_wav_is_not_16khz_mono_or_clips_run_short(tmp_path: Path) -> None:
    _write_wav(tmp_path / "x.wav", 100, rate=8000)
    with pytest.raises(SystemExit):
        bench_stt.read_wav(tmp_path / "x.wav")
    with pytest.raises(SystemExit):
        bench_stt.load_m0a(_m0a_dir(tmp_path, ["jarvis_command"]), 2)
