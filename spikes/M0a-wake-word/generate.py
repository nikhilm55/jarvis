"""M0a: synthesise the wake-word evaluation set with Piper TTS (many voices, speeds, noise levels).

Usage (throwaway env, nothing added to the project):
  uv run --no-project --python 3.11 --with openwakeword==0.6.0 --with piper-tts==1.8.0 \
      --with onnxruntime==1.30.0 python spikes/M0a-wake-word/generate.py
  (resolved on 2026-10-07: python 3.11.15, numpy 2.4.6, scipy 1.17.1)
Writes 16 kHz mono WAVs + manifest.csv to spikes/M0a-wake-word/data/clips/ (gitignored).
Synthetic voices only — real-voice calibration happens in the setup wizard (FR-ACT-15).
"""

from __future__ import annotations

import csv
import random
import re
import sys
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = HERE / "data"
VOICES = DATA / "models" / "piper"
OUT = DATA / "clips"
RATE = 16_000
sys.path.insert(0, str(HERE))
from record import COMMANDS, MID_SENTENCE  # noqa: E402 — share the prompt lists

CONFUSABLE = ["Travis", "Service", "Nervous", "Elvis", "Davis", "Garvey", "Harvest", "Jars of"]
CASUAL = [
    "Can you send me the slides before the call",
    "I think the build is broken again",
    "Let's grab lunch after the standup",
    "The client wants the release moved to Friday",
    "Did anyone check the logs from last night",
    "My internet keeps dropping today",
    "We should write a test for that edge case",
    "Please share your screen for a second",
    "I'll be ten minutes late to the meeting",
    "The weather is lovely this morning",
    "Open the document and scroll to page four",
    "Remind me to call my mother later",
    "What did the manager say about the budget",
    "Turn the volume down a little",
    "The coffee machine is broken again",
    "I'm going to restart my laptop now",
]
COUNTS = {"jarvis_command": 300, "jarvis_alone": 100, "jarvis_mid_sentence": 200, "confusable": 200}
NEGATIVE_MINUTES = 60


def frs_sentences() -> list[str]:
    """Plain English sentences from the FRS without the wake word: varied negative speech."""
    text = (ROOT / "docs" / "FRS.md").read_text(encoding="utf-8")
    text = re.sub(r"[`*_|#>\[\]()]|\bFR-[A-Z]+-\d+\b|https?://\S+", " ", text)
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        words = sentence.split()
        if 5 <= len(words) <= 22 and "jarvis" not in sentence.lower() and sentence.isascii():
            out.append(" ".join(words))
    return out


def noise(kind: str, n: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(n)
    if kind == "white":
        return white
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1]
    spectrum /= np.sqrt(freqs) if kind == "pink" else freqs  # pink 1/f, brown 1/f²
    return np.fft.irfft(spectrum, n)


def synth(voice: PiperVoice, text: str, speaker: int | None, length_scale: float) -> np.ndarray:
    config = SynthesisConfig(
        speaker_id=speaker, length_scale=length_scale, noise_scale=0.667, noise_w_scale=0.8
    )
    chunks = [
        np.asarray(chunk.audio_float_array, dtype=np.float32)
        for chunk in voice.synthesize(text, config)
    ]
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    return resample_poly(audio, RATE, voice.config.sample_rate).astype(np.float32)


def assemble(
    speech: np.ndarray, rng: np.random.Generator, lead: float
) -> tuple[np.ndarray, str, float | None]:
    audio = np.concatenate([np.zeros(int(lead * RATE)), speech, np.zeros(int(0.5 * RATE))])
    kind = rng.choice(["none", "pink", "brown", "white"], p=[0.25, 0.35, 0.25, 0.15])
    snr = None
    if kind != "none":
        snr = float(rng.choice([20.0, 10.0, 5.0]))
        n = noise(kind, len(audio), rng)
        speech_rms = np.sqrt(np.mean(speech**2)) + 1e-9
        n *= speech_rms / (np.sqrt(np.mean(n**2)) + 1e-9) / (10 ** (snr / 20))
        audio = audio + n
    audio *= 0.9 / max(1e-6, float(np.max(np.abs(audio))))
    return audio, kind, snr


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def main() -> int:
    rng = np.random.default_rng(42)
    pick = random.Random(42)  # noqa: S311 — reproducible dataset, not security
    voices = {p.stem: PiperVoice.load(str(p)) for p in sorted(VOICES.glob("*.onnx"))}
    negatives = frs_sentences() + CASUAL * 3
    plan: list[tuple[str, str]] = []
    plan += [
        ("jarvis_command", f"Jarvis, {pick.choice(COMMANDS)}")
        for _ in range(COUNTS["jarvis_command"])
    ]
    plan += [("jarvis_alone", "Jarvis.") for _ in range(COUNTS["jarvis_alone"])]
    plan += [
        ("jarvis_mid_sentence", pick.choice(MID_SENTENCE))
        for _ in range(COUNTS["jarvis_mid_sentence"])
    ]
    plan += [
        ("confusable", f"{pick.choice(CONFUSABLE)}, {pick.choice(COMMANDS)}")
        for _ in range(COUNTS["confusable"])
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    rows, negative_seconds, i = [], 0.0, 0
    with (OUT / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "clip",
                "category",
                "text",
                "voice",
                "speaker",
                "length_scale",
                "noise",
                "snr_db",
                "seconds",
            ]
        )

        def emit(category: str, text: str) -> float:
            nonlocal i
            name = pick.choice(list(voices))
            voice = voices[name]
            speaker = (
                pick.randrange(voice.config.num_speakers) if voice.config.num_speakers > 1 else None
            )
            length_scale = round(pick.uniform(0.8, 1.3), 2)
            audio, kind, snr = assemble(
                synth(voice, text, speaker, length_scale), rng, lead=pick.uniform(0.6, 1.2)
            )
            clip = f"{category}-{i:05d}"
            write_wav(OUT / category / f"{clip}.wav", audio)
            seconds = len(audio) / RATE
            writer.writerow(
                [clip, category, text, name, speaker, length_scale, kind, snr, f"{seconds:.2f}"]
            )
            i += 1
            return seconds

        for n, (category, text) in enumerate(plan, 1):
            emit(category, text)
            if n % 100 == 0:
                print(f"  {n}/{len(plan)} wake-word clips", flush=True)
        while negative_seconds < NEGATIVE_MINUTES * 60:
            negative_seconds += emit("negative_speech", pick.choice(negatives))
            rows.append(1)
            if len(rows) % 200 == 0:
                print(
                    f"  negative speech {negative_seconds / 60:.1f}/{NEGATIVE_MINUTES} min",
                    flush=True,
                )
    print(
        f"done: {i} clips, {negative_seconds / 60:.1f} min negative speech, {len(voices)} voice packs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
