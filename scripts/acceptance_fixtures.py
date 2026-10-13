"""Generate acceptance test fixtures for the Jarvis voice assistant."""

from __future__ import annotations

import argparse
import json
import math
import wave
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from jarvis.audio.sources import SAMPLE_RATE, Pcm
from jarvis.config import TtsSettings
from jarvis.tts.engines import AudioEngine, default_engine

LEAD_S: float = 1.2
TAIL_S: float = 0.2
PHRASES: dict[str, str] = {
    "open-calculator": "Jarvis, open Calculator.",
    "close-calculator": "Jarvis, close Calculator.",
    "what-time": "Jarvis, what time is it?",
    "volume-up": "Jarvis, volume up.",
    "volume-set": "Jarvis, set volume to 30 percent.",
    "brain-open": "Jarvis, please open the calculator app for me.",
    "brain-close": "Jarvis, close it.",
    "wake-only": "Jarvis.",
    "listen-open": "Open Calculator.",
    "mid-sentence": "I told Jarvis to open Calculator.",
}
FIXTURES: tuple[tuple[str, str], ...] = (
    ("open-calculator", "am_michael"),
    ("open-calculator", "af_heart"),
    ("close-calculator", "am_michael"),
    ("close-calculator", "af_heart"),
    ("what-time", "am_michael"),
    ("what-time", "af_heart"),
    ("volume-up", "am_michael"),
    ("volume-up", "af_heart"),
    ("volume-set", "am_michael"),
    ("brain-open", "af_heart"),
    ("brain-close", "am_michael"),
    ("wake-only", "am_michael"),
    ("listen-open", "af_heart"),
    ("mid-sentence", "am_michael"),
)

_ENGINE_CACHE: dict[str, AudioEngine] = {}


def fixture_name(phrase_id: str, voice: str) -> str:
    """Return the fixture file name stem for a phrase and voice."""
    return f"{phrase_id}-{voice}"


def resample(audio: npt.NDArray[np.float32], rate: int) -> npt.NDArray[np.float32]:
    """Resample mono float audio to 16 kHz using a windowed-sinc FIR filter."""
    if rate == SAMPLE_RATE:
        return audio.astype(np.float32, copy=True)
    g = math.gcd(SAMPLE_RATE, rate)
    up = SAMPLE_RATE // g
    down = rate // g
    taps = 101
    nyq = min(SAMPLE_RATE, rate) / 2.0
    cutoff = nyq * 0.95
    n = np.arange(taps)
    mid = (taps - 1) / 2.0
    sinc = np.sinc((n - mid) * 2.0 * cutoff / (rate * up))  # cutoff relative to rate*up
    window = np.hanning(taps)
    kernel = (sinc * window).astype(np.float32)
    kernel *= up
    kernel /= np.sum(kernel)
    upsampled = np.zeros(audio.size * up, dtype=np.float32)
    upsampled[::up] = audio
    filtered = np.convolve(upsampled, kernel, mode="same")
    return filtered[::down].astype(np.float32, copy=False)


def to_pcm(audio: npt.NDArray[np.float32]) -> Pcm:
    """Scale float audio to a peak of 0.8 and convert to int16 PCM."""
    if audio.size == 0:
        return np.zeros(0, dtype=np.int16)
    peak = float(np.max(np.abs(audio)))
    if peak == 0.0:
        return np.zeros(audio.size, dtype=np.int16)
    scaled = (audio / peak * 0.8).astype(np.float32)
    np.clip(scaled, -1.0, 1.0, out=scaled)
    return np.round(scaled * 32767).astype(np.int16)


def trim_silence(pcm: Pcm, floor: int = 300) -> Pcm:
    """Drop the near-silent samples (below `floor`) at both ends, so the speech end is exact."""
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) >= floor)
    if loud.size == 0:
        return pcm
    return pcm[loud[0] : loud[-1] + 1]


def with_silence(speech: Pcm) -> tuple[Pcm, float]:
    """Prepend and append silence to speech and return the end timestamp."""
    lead = int(LEAD_S * SAMPLE_RATE)
    tail = int(TAIL_S * SAMPLE_RATE)
    pcm = np.concatenate([np.zeros(lead, dtype=np.int16), speech, np.zeros(tail, dtype=np.int16)])
    end_s = LEAD_S + len(speech) / SAMPLE_RATE
    return pcm, end_s


def write_wav(path: Path, pcm: Pcm) -> None:
    """Write a 16 kHz mono 16-bit WAV file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


def generate(
    out_dir: Path,
    synthesize: Callable[[str, str], tuple[npt.NDArray[np.float32], int]],
) -> dict[str, dict[str, object]]:
    """Generate all fixture WAV files and the manifest, returning the manifest."""
    manifest: dict[str, dict[str, object]] = {}
    for phrase_id, voice in FIXTURES:
        name = fixture_name(phrase_id, voice)
        audio, rate = synthesize(PHRASES[phrase_id], voice)
        speech = trim_silence(to_pcm(resample(audio, rate)))
        pcm, end_s = with_silence(speech)
        write_wav(out_dir / f"{name}.wav", pcm)
        manifest[name] = {
            "text": PHRASES[phrase_id],
            "voice": voice,
            "speech_end_s": round(end_s, 3),
            "duration_s": round(len(pcm) / SAMPLE_RATE, 3),
        }
    manifest_path = out_dir / "manifest.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def kokoro_synthesize(text: str, voice: str) -> tuple[npt.NDArray[np.float32], int]:
    """Synthesize text with Kokoro, caching one engine per voice."""
    if voice not in _ENGINE_CACHE:
        engine = default_engine(TtsSettings(voice=voice))
        if not isinstance(engine, AudioEngine):
            raise RuntimeError(f"Kokoro is not available: {engine!r}")
        _ENGINE_CACHE[voice] = engine
    engine = _ENGINE_CACHE[voice]
    return engine.synthesize(text), engine.sample_rate


def main(argv: Sequence[str] | None = None) -> int:
    """Generate acceptance fixtures and print a summary line per fixture."""
    parser = argparse.ArgumentParser(description="Generate acceptance fixtures.")
    default_out = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "acceptance"
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args(argv)
    manifest = generate(args.out, kokoro_synthesize)
    for name, entry in manifest.items():
        print(f"{name}: {entry['duration_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
