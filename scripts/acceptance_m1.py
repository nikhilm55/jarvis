"""M1 acceptance, Part A: scripted speech through the real voice pipeline on this machine.

Needs JARVIS_HOME (a scratch home that already holds the models; never the real one) and
JARVIS_WHISPER_SERVER. Fixtures come from scripts/acceptance_fixtures.py. Real components:
VAD, wake model, whisper-server, Kokoro, fast path, desktop worker, Claude Code brain, and the
product's own PortAudio sink (wrapped only to time the first sound).
"""

import argparse
import asyncio
import json
import logging
import os
import platform
import sys
import time
import wave
from collections.abc import Sequence
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from unittest import mock

from acceptance_audio import (
    PlaybackLog,
    QueueSource,
    recording_sink_factory,
)
from acceptance_harness import (
    EOS_SETTLE_S,
    FAST_TIMEOUT_S,
    MAX_BRAIN_TURNS,
    BrainGate,
    CapturingLog,
    Harness,
    calc_is,
    calculator_windows,
    judge,
    judge_dropped,
    turn_case,
)
from acceptance_idle import IdleResult, measure_idle, noise_pcm, silence_pcm
from acceptance_report import (
    Row,
    results_table,
    spoken_time_matches,
    summary_table,
)

from jarvis.activity import TurnRecord
from jarvis.audio import WavFileSource
from jarvis.audio.sources import SAMPLE_RATE
from jarvis.config import load_settings
from jarvis.desktop.volume import VolumeState, set_mute, volume_get, volume_set
from jarvis.desktop.x11 import close_window
from jarvis.fastpath import execute
from jarvis.orchestrator import assemble, turns
from jarvis.orchestrator.assemble import build_components, build_segmenter
from jarvis.orchestrator.core import Orchestrator
from jarvis.orchestrator.hud import HudEvent
from jarvis.tts import Speaker
from jarvis.tts.sink import SoundDeviceSink

ROOT = Path(__file__).resolve().parent.parent


def volume_pct() -> int:
    """The default sink volume right now, in percent."""
    return volume_get().percent


async def run_fast_cases(h: Harness) -> None:
    """Open/close Calculator, the time, and volume: three runs each, two voices."""
    voices = ("am_michael", "af_heart", "am_michael")

    async def opened(_r: TurnRecord) -> str | None:
        return await calc_is(True, h)

    async def closed(_r: TurnRecord) -> str | None:
        return await calc_is(False, h)

    async def timed(r: TurnRecord) -> str | None:
        spoken = r.final.spoken if r.final else ""
        return None if spoken_time_matches(spoken, datetime.now()) else f"spoke {spoken!r}"

    for run, voice in enumerate(voices, 1):
        await turn_case(h, "open-calculator", run, f"open-calculator-{voice}", "fastpath", opened)
        await turn_case(h, "close-calculator", run, f"close-calculator-{voice}", "fastpath", closed)
    for run, voice in enumerate(voices, 1):
        await turn_case(h, "what-time", run, f"what-time-{voice}", "fastpath", timed)
    volume_set(50)

    async def set_30(_r: TurnRecord) -> str | None:
        now = await asyncio.to_thread(volume_pct)
        return None if now == 30 else f"volume is {now}%, expected 30%"

    await turn_case(h, "volume-set-30", 1, "volume-set-am_michael", "fastpath", set_30)
    for run, voice in enumerate(voices, 1):
        before = volume_pct()

        async def stepped(_r: TurnRecord, before: int = before) -> str | None:
            now = await asyncio.to_thread(volume_pct)
            return None if now > before else f"volume went {before}% -> {now}%"

        await turn_case(h, "volume-up", run, f"volume-up-{voice}", "fastpath", stepped)


async def run_brain_cases(h: Harness) -> None:
    """The two brain-routed turns (the only live brain turns of the run)."""

    async def opened(_r: TurnRecord) -> str | None:
        return await calc_is(True, h)

    async def closed(_r: TurnRecord) -> str | None:
        return await calc_is(False, h)

    await turn_case(h, "brain-open", 1, "brain-open-af_heart", "brain", opened)
    await turn_case(h, "brain-close-it", 1, "brain-close-am_michael", "brain", closed)


async def run_window_cases(h: Harness) -> None:
    """A bare 'Jarvis.', then the command in the listen window; then a mid-sentence mention."""
    seen_turns, seen_hud = len(h.log.turns()), len(h.hud)
    await h.say("wake-only-am_michael")
    opened = await h.hud_event("listening", seen_hud, 20.0)
    eos = await h.say("listen-open-af_heart") if opened else time.monotonic()
    record = await h.new_turn(seen_turns, FAST_TIMEOUT_S) if opened else None
    problem = await calc_is(True, h) if record is not None else "the listen window never opened"
    h.add("listen-window", 1, record, judge("fastpath", record, problem), eos)
    for window in calculator_windows():
        close_window(window.window_id)
    await h.until(lambda: not calculator_windows(), 6.0)

    seen_turns, seen_records = len(h.log.turns()), len(h.log.records)
    eos = await h.say("mid-sentence-am_michael")
    await asyncio.sleep(EOS_SETTLE_S + max(0.0, eos - time.monotonic()))
    ran = len(h.log.turns()) > seen_turns
    dropped = h.log.records[seen_records:]
    problem = judge_dropped(ran, bool(calculator_windows()), dropped)
    note = dropped[-1] if dropped else None
    outcome = "PASS" if problem is None else f"FAIL: {problem}"
    h.add("mid-sentence", 1, note, outcome, eos)


def idle_runs(seconds: float) -> list[IdleResult]:
    """Capture + VAD + wake scoring on silence and on noise, in real time, per FRS 7.1."""
    settings = load_settings()
    segmenter = build_segmenter(settings, lambda: False)
    scratch = Path(os.environ["JARVIS_HOME"]) / "idle"
    scratch.mkdir(parents=True, exist_ok=True)
    results = []
    for label, pcm in (
        ("silence", silence_pcm(seconds)),
        ("noise", noise_pcm(seconds)),
    ):
        path = scratch / f"{label}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm.tobytes())
        source = WavFileSource(path, realtime=True)
        results.append(measure_idle(label, source.frames(), lambda f: len(segmenter.feed(f))))
        source.close()
    return results


def idle_table(results: Sequence[IdleResult]) -> str:
    """Markdown for the idle-CPU results."""
    lines = [
        "| Input | Seconds | Frames | CPU s | % of one core | Segments |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.label} | {r.wall_s:.1f} | {r.frames} | {r.cpu_s:.2f} | {r.percent} | {r.segments} |"
        for r in results
    ]
    return "\n".join(lines)


async def run_suite(
    fixtures: Path, include_brain: bool, verbose: bool, output_latency: str | float | None = None
) -> tuple[list[Row], list[str]]:
    """Build the real components, run every case, and always clean up."""
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    settings = load_settings()
    source = QueueSource()
    playback = PlaybackLog()
    log = CapturingLog()
    harness = Harness(source, log, playback, manifest, fixtures)
    latency = settings.tts.output_latency if output_latency is None else output_latency
    sink_factory = recording_sink_factory(partial(SoundDeviceSink, latency=latency), playback)

    def make_speaker(tts: Any, engine_factory: Any) -> Speaker:
        return Speaker(tts, engine_factory=engine_factory, sink_factory=sink_factory)

    async def timed_execute(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            return await execute(*args, **kwargs)
        finally:
            harness.exec_ms.append(round((time.monotonic() - started) * 1000))

    async def hud(event: HudEvent) -> None:
        harness.hud.append((time.monotonic(), event))
        if verbose:
            print(f"  hud {time.monotonic():.2f} {event.state}: {event.text}", file=sys.stderr)

    with (
        mock.patch.object(assemble, "Speaker", make_speaker),
        mock.patch.object(turns, "execute", timed_execute),
    ):
        parts = await build_components(settings, source, mode="balanced", with_brain=include_brain)
        gate = BrainGate(parts.brain) if parts.brain is not None else None
        if gate is not None:
            parts.brain = gate
        orchestrator = Orchestrator(settings, parts, mode="balanced", hud=hud, activity=log)
        task = asyncio.create_task(orchestrator.run())
        calculator_left = False
        try:
            await asyncio.to_thread(source.started.wait, 120.0)
            for window in calculator_windows():
                close_window(window.window_id)
            await run_fast_cases(harness)
            if gate is not None:
                gate.open = True
                try:
                    await run_brain_cases(harness)
                finally:
                    gate.open = False
            await run_window_cases(harness)
        finally:
            for window in calculator_windows():
                close_window(window.window_id)
            orchestrator.request_stop()
            await asyncio.wait_for(task, 60.0)
            calculator_left = not await harness.until(lambda: not calculator_windows(), 6.0)
    return harness.rows, suite_notes(harness, log, gate, calculator_left)


def suite_notes(
    harness: Harness, log: CapturingLog, gate: BrainGate | None, calculator_left: bool
) -> list[str]:
    """What the run saw besides the rows; a line starting PROBLEM fails the run."""
    notes = [f"first sound was an earcon in {len(harness.earcon_first)} of {len(harness.rows)}"]
    notes.append(
        f"brain turns run: {sum(r.route == 'brain' for r in log.turns())} (cap {MAX_BRAIN_TURNS})"
    )
    if gate is not None and gate.refused:
        notes.append(
            f"{gate.refused} brain turn(s) refused outside the brain cases or over the cap"
        )
    if calculator_left:
        notes.append("PROBLEM: Calculator was still open at the end")
    errors = [e.text for _, e in harness.hud if e.state == "error"]
    return notes + [f"HUD error: {text}" for text in dict.fromkeys(errors)]


def restore_audio(start: VolumeState) -> list[str]:
    """Put the volume and the mute back, each on its own, and read both back."""
    problems: list[str] = []
    try:
        volume_set(start.percent)
        now = volume_get().percent
        if now != start.percent:
            problems.append(f"volume is {now}% after restoring, expected {start.percent}%")
    except Exception as error:  # a failed restore must not hide the mute restore
        problems.append(f"volume could not be restored: {error}")
    try:
        set_mute(start.muted)
        muted = volume_get().muted
        if muted != start.muted:
            problems.append(f"mute is {muted} after restoring, expected {start.muted}")
    except Exception as error:
        problems.append(f"mute could not be restored: {error}")
    return problems


def environment_lines(start: VolumeState, latency: str | float | None) -> list[str]:
    """Where and with what this ran."""
    chosen = "the product's own setting (tts.output_latency)" if latency is None else repr(latency)
    return [
        f"- Host: {platform.node()}, {platform.platform()}, Python {platform.python_version()}",
        f"- Playback: the product's PortAudio sink (SoundDeviceSink), first-write timing, "
        f"output latency: {chosen}",
        f"- Starting volume (restored at the end): {start.percent}%"
        f"{' (muted)' if start.muted else ''}",
        f"- Run at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
    ]


def parse_latency(text: str) -> str | float:
    """`low`, `high` or a number of seconds."""
    return text if text in ("low", "high") else float(text)


def main(argv: Sequence[str] | None = None) -> int:
    """Run Part A and print the report sections."""
    parser = argparse.ArgumentParser(description="M1 acceptance, Part A.")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests" / "fixtures" / "acceptance")
    parser.add_argument("--idle-s", type=float, default=60.0, help="seconds per idle-CPU input")
    parser.add_argument("--no-suite", action="store_true", help="idle CPU only")
    parser.add_argument("--no-idle", action="store_true", help="skip idle CPU")
    parser.add_argument("--no-brain", action="store_true", help="skip the two brain turns")
    parser.add_argument(
        "--output-latency",
        type=parse_latency,
        default=None,
        help="PortAudio output latency (low, high or seconds); default: the product's setting",
    )
    parser.add_argument("--verbose", action="store_true", help="HUD events and logs on stderr")
    parser.add_argument("--out", type=Path, help="also write the report here")
    args = parser.parse_args(argv)
    if not os.environ.get("JARVIS_HOME"):
        print(
            "acceptance: set JARVIS_HOME to a scratch home (never your real data)", file=sys.stderr
        )
        return 2
    if args.verbose:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    start = volume_get()
    sections = ["## Environment", *environment_lines(start, args.output_latency)]
    code = 0
    try:
        if not args.no_idle:
            sections += ["", "## Idle CPU", idle_table(idle_runs(args.idle_s))]
        if not args.no_suite:
            rows, notes = asyncio.run(
                run_suite(args.fixtures, not args.no_brain, args.verbose, args.output_latency)
            )
            failed = [r for r in rows if not r.passed]
            code = 1 if failed or any(n.startswith("PROBLEM") for n in notes) else 0
            sections += [
                "",
                "## Results",
                results_table(rows),
                "",
                "## Summary",
                summary_table(rows),
            ]
            sections += ["", f"{len(rows) - len(failed)}/{len(rows)} runs passed", *notes]
    finally:
        problems = restore_audio(start)
    for problem in problems:
        sections.append(f"PROBLEM: {problem}")
        code = 1
    report = "\n".join(sections)
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
