import importlib.util
import json
import sys
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "acceptance_fixtures", ROOT / "scripts" / "acceptance_fixtures.py"
)
assert spec and spec.loader
fixtures = importlib.util.module_from_spec(spec)
sys.modules["acceptance_fixtures"] = fixtures
spec.loader.exec_module(fixtures)


def test_should_resample_1khz_sine_to_16khz_when_input_is_24khz() -> None:
    t = np.arange(12000, dtype=np.float32) / 24000.0
    sine = np.sin(2.0 * np.pi * 1000.0 * t).astype(np.float32)
    out = fixtures.resample(sine, 24000)
    assert abs(len(out) - 8000) <= 1
    n = len(out)
    spectrum = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(n, 1.0 / 16000.0)
    peak_hz = freqs[np.argmax(spectrum)]
    assert abs(peak_hz - 1000.0) <= 20.0


def test_should_return_equal_copy_when_rate_is_already_16000() -> None:
    audio = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    out = fixtures.resample(audio, 16000)
    assert out is not audio
    assert np.array_equal(out, audio)


def test_should_scale_peak_to_0_8_when_converting_float_to_pcm() -> None:
    pcm = fixtures.to_pcm(np.array([0.0, 0.5, -0.25], dtype=np.float32))
    expected = round(0.8 * 32767)
    assert abs(int(np.max(np.abs(pcm))) - expected) <= 1


def test_should_strip_quiet_ends_when_trimming_silence() -> None:
    pcm = np.array([0, 10, 5000, -4000, 20, 0], dtype=np.int16)
    out = fixtures.trim_silence(pcm)
    assert np.array_equal(out, np.array([5000, -4000], dtype=np.int16))


def test_should_pad_silence_and_compute_end_when_wrapping_speech() -> None:
    speech = np.ones(16000, dtype=np.int16)
    pcm, end_s = fixtures.with_silence(speech)
    assert len(pcm) == 16000 + 19200 + 3200
    assert abs(end_s - 2.2) < 1e-6


def test_should_write_wavs_and_manifest_when_generating_with_fake_synth(tmp_path: Path) -> None:
    def fake_synth(text: str, voice: str) -> tuple[npt.NDArray[np.float32], int]:
        t = np.arange(7200, dtype=np.float32) / 24000.0
        audio = (0.5 * np.sin(2.0 * np.pi * 1000.0 * t)).astype(np.float32)
        return audio, 24000

    manifest = fixtures.generate(tmp_path, fake_synth)
    for phrase_id, voice in fixtures.FIXTURES:
        name = fixtures.fixture_name(phrase_id, voice)
        wav_path = tmp_path / f"{name}.wav"
        assert wav_path.exists()
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(parsed.keys()) == set(manifest.keys())
    first_id, first_voice = fixtures.FIXTURES[0]
    first_name = fixtures.fixture_name(first_id, first_voice)
    with wave.open(str(tmp_path / f"{first_name}.wav"), "rb") as wf:
        lead_samples = wf.readframes(int(fixtures.LEAD_S * 16000))
    assert all(b == 0 for b in lead_samples)


def test_should_have_unique_names_and_known_phrases_when_listing_fixtures() -> None:
    names = [fixtures.fixture_name(pid, v) for pid, v in fixtures.FIXTURES]
    assert len(names) == len(set(names))
    for pid, _ in fixtures.FIXTURES:
        assert pid in fixtures.PHRASES
