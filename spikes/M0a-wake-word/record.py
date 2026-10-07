"""M0a: guided recording of the owner's own voice for the wake-word evaluation (~15 minutes).

Usage:  python3 spikes/M0a-wake-word/record.py            (resume-safe: skips clips already recorded)
        python3 spikes/M0a-wake-word/record.py --list     (show the plan without recording)

Records 16 kHz mono 16-bit WAV with PipeWire's `pw-record` into spikes/M0a-wake-word/data/
(gitignored — never committed, policy §2). Only the owner's own voice; no other people.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
COMMANDS = [
    "open Teams",
    "read me all my unread messages",
    "what's on my calendar today",
    "write a message to Rahul saying I'll be ten minutes late",
    "set volume to thirty",
    "open my chat with Priya",
    "what time is it",
    "lock my screen",
    "close Chrome",
    "summarise this",
    "remind me in twenty minutes to call Arjun",
    "turn on do not disturb",
    "find the invoice PDF I downloaded yesterday",
    "take a screenshot",
    "start my day",
    "mute",
    "next track",
    "open Settings",
    "how much battery do I have",
    "stop",
]
MID_SENTENCE = [
    "I asked Jarvis yesterday and it worked fine",
    "the movie where Jarvis helps Tony Stark is my favourite",
    "do you think Jarvis can handle Teams messages",
    "we named the project Jarvis because of Iron Man",
    "I was telling Rahul that Jarvis is almost ready",
    "can you check whether Jarvis logged that error",
]


def plan() -> list[tuple[str, str, float, str]]:
    """(clip id, category, seconds, what to say). Deterministic order, mixed styles."""
    rng = random.Random(7)  # noqa: S311 — deterministic prompt order, not security
    clips: list[tuple[str, str, float, str]] = []
    styles = ["normal speed", "fast, one breath", "slowly", "from arm's length", "quietly"]
    for i in range(50):
        command = COMMANDS[i % len(COMMANDS)]
        clips.append(
            (f"cmd-{i:02d}", "jarvis_command", 4.5, f'"Jarvis, {command}"  ({rng.choice(styles)})')
        )
    for i in range(20):
        clips.append((f"alone-{i:02d}", "jarvis_alone", 2.5, f'"Jarvis"  ({rng.choice(styles)})'))
    for i in range(30):
        clips.append(
            (f"mid-{i:02d}", "jarvis_mid_sentence", 5.0, f'"{MID_SENTENCE[i % len(MID_SENTENCE)]}"')
        )
    clips.append(
        (
            "ambient-00",
            "negative_ambient",
            300.0,
            "5 minutes of NORMAL activity: type, talk on a call or to yourself WITHOUT saying Jarvis, play a video",
        )
    )
    return clips


def record(path: Path, seconds: float) -> bool:
    proc = subprocess.Popen(
        ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            left = end - time.monotonic()
            print(f"\r  ● recording … {left:4.1f} s ", end="", flush=True)
            time.sleep(0.1)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    print("\r  ✓ saved" + " " * 20)
    return path.exists() and path.stat().st_size > 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    clips = plan()
    if args.list:
        for clip_id, category, seconds, say in clips:
            print(f"{clip_id:11} {category:20} {seconds:5.1f}s  {say}")
        print(f"total ≈ {sum(c[2] for c in clips) / 60:.1f} min of audio")
        return 0
    if not shutil.which("pw-record"):
        print("pw-record not found (PipeWire). Install pipewire-bin.")
        return 1
    DATA.mkdir(exist_ok=True)
    manifest = DATA / "manifest.csv"
    new = not manifest.exists()
    todo = [c for c in clips if not (DATA / f"{c[0]}.wav").exists()]
    print(
        f"{len(clips) - len(todo)} of {len(clips)} clips already recorded. Ctrl+C any time — re-run to resume.\n"
    )
    with manifest.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["clip", "category", "seconds", "prompt"])
        for n, (clip_id, category, seconds, say) in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] {category}\n  Say: {say}")
            answer = input("  Enter = record · s = skip · q = quit: ").strip().lower()
            if answer == "q":
                break
            if answer == "s":
                continue
            time.sleep(0.3)  # let the keypress sound fade
            if record(DATA / f"{clip_id}.wav", seconds):
                writer.writerow([clip_id, category, seconds, say])
                handle.flush()
    done = sum(1 for c in clips if (DATA / f"{c[0]}.wav").exists())
    print(f"\n{done}/{len(clips)} clips recorded in {DATA}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped — re-run to resume.")
        sys.exit(0)
