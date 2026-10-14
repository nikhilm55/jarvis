"""Command-line entry point. Grows into `jarvis doctor`, `jarvis ptt`, … (FRS §5.17)."""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from jarvis import __version__, models
from jarvis.audio import (
    SAMPLE_RATE,
    AudioDeviceError,
    AudioFormatError,
    AudioSource,
    Endpointer,
    MicSource,
    SileroVad,
    SpeechStart,
    Utterance,
    WavFileSource,
)
from jarvis.config import ConfigError, Settings, load_settings
from jarvis.hud.runtime import running_hud
from jarvis.orchestrator.assemble import build_components
from jarvis.orchestrator.core import Orchestrator
from jarvis.orchestrator.hud import HudEvent, HudSink
from jarvis.policy import Mode
from jarvis.stt import SttUnavailable
from jarvis.tts import Speaker
from jarvis.tts.earcons import EARCON_NAMES


async def _print_hud(event: HudEvent) -> None:
    print(f"[{event.state}] {event.text}".rstrip(), flush=True)


def _tee(first: HudSink, second: HudSink | None) -> HudSink:
    if second is None:
        return first

    async def both(event: HudEvent) -> None:
        await first(event)
        await second(event)

    return both


async def _run_loop(
    settings: Settings, source: AudioSource, mode: Mode, with_brain: bool, hud: bool
) -> None:
    # `build_components` is looked up in this module's globals, so tests can replace it.
    parts = await build_components(settings, source, mode=mode, with_brain=with_brain)
    async with running_hud(settings.hud, enabled=hud) as sink:
        await Orchestrator(settings, parts, mode=mode, hud=_tee(_print_hud, sink)).run()


def _cmd_run(args: argparse.Namespace) -> int:
    source: AudioSource | None = None
    try:
        settings = load_settings()
        source = (
            WavFileSource(args.source, realtime=True)
            if args.source
            else MicSource(settings.audio.device)
        )
        asyncio.run(_run_loop(settings, source, args.mode, not args.no_brain, not args.no_hud))
    except (
        ConfigError,
        AudioDeviceError,
        AudioFormatError,
        SttUnavailable,
        httpx.HTTPError,
        models.ModelIntegrityError,
    ) as e:
        print(f"jarvis run: {e}", file=sys.stderr)
        return 2
    finally:
        if source is not None:
            source.close()
    return 0


def _cmd_say(args: argparse.Namespace) -> int:
    if bool(args.text) == bool(args.earcon):
        print("jarvis say: give TEXT or --earcon NAME", file=sys.stderr)
        return 2
    speaker = Speaker(load_settings().tts)
    try:
        handle = speaker.earcon(args.earcon) if args.earcon else speaker.say(args.text)
        handle.wait()
        if handle.first_audio_s is None:
            print("jarvis say: no audio was produced (see the log)", file=sys.stderr)
            return 1
        if not args.earcon:
            print(f"first audio: {round(handle.first_audio_s * 1000)} ms")
        return 0
    finally:
        speaker.close()


def _cmd_listen(args: argparse.Namespace) -> int:
    audio = load_settings().audio
    source: AudioSource = WavFileSource(args.source) if args.source else MicSource(audio.device)
    try:
        endpointer = Endpointer(SileroVad(), trailing_ms=audio.trailing_ms, cap_s=audio.cap_s)
        silence_before_ms = 0
        for frame in source.frames():
            for event in endpointer.feed(frame):
                if isinstance(event, SpeechStart):
                    silence_before_ms = event.silence_before_ms
                else:
                    return _print_utterance(event, silence_before_ms)
        for event in endpointer.flush():
            if isinstance(event, Utterance):
                return _print_utterance(event, silence_before_ms)
    except (AudioFormatError, AudioDeviceError, httpx.HTTPError, models.ModelIntegrityError) as e:
        print(f"jarvis listen: {e}", file=sys.stderr)
        return 2
    finally:
        source.close()
    print("jarvis listen: no speech heard", file=sys.stderr)
    return 1


def _print_utterance(utterance: Utterance, silence_before_ms: int) -> int:
    length = len(utterance.pcm) / SAMPLE_RATE
    print(
        f"utterance length={length:.2f}s silence_before_ms={silence_before_ms} "
        f"started_at={utterance.started_at:.2f}s ended_at={utterance.ended_at:.2f}s"
    )
    return 0


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _cmd_models_list(_args: argparse.Namespace) -> int:
    for spec in models.REGISTRY.values():
        path = models.model_path(spec)
        size = _human_size(path.stat().st_size) if path.is_file() else ""
        print(f"{spec.name:<20} {spec.filename:<24} {size}".rstrip())
    return 0


def _cmd_models_fetch(args: argparse.Namespace) -> int:
    try:
        specs = [models.get_spec(name) for name in args.names or models.REGISTRY]
    except models.UnknownModelError as error:
        print(f"jarvis models fetch: {error}", file=sys.stderr)
        return 2
    for spec in specs:
        if args.dry_run:
            state = "cached" if models.is_cached(spec) else "would download"
            print(f"{state} {spec.name}: {spec.url} -> {models.model_path(spec)}")
            continue
        try:
            print(f"{spec.name}: {models.ensure(spec.name)}")
        except (httpx.HTTPError, models.ModelIntegrityError) as error:
            print(f"jarvis models fetch: {spec.name}: {error}", file=sys.stderr)
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Voice control for your whole PC.")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="{run,say,listen,models}")
    run = commands.add_parser("run", help="run the voice loop")
    run.add_argument("--source", type=Path, metavar="FILE.wav", help="read a WAV, not the mic")
    run.add_argument("--mode", choices=("safe", "balanced", "yolo"), default="balanced")
    run.add_argument("--no-brain", action="store_true", help="fast path only; no Claude Code")
    run.add_argument("--no-hud", action="store_true", help="no on-screen HUD pill")
    run.set_defaults(handler=_cmd_run)
    say = commands.add_parser("say", help="speak a line of text")
    say.add_argument("text", nargs="?", default=None)
    say.add_argument("--earcon", choices=EARCON_NAMES, metavar="NAME", default=None)
    say.set_defaults(handler=_cmd_say)
    listen = commands.add_parser("listen", help="capture one utterance and report its timings")
    listen.add_argument(
        "--once", action="store_true", required=True, help="stop after one utterance"
    )
    listen.add_argument("--source", type=Path, metavar="FILE.wav", help="read a WAV, not the mic")
    listen.set_defaults(handler=_cmd_listen)
    models_parser = commands.add_parser("models", help="list or download model files")
    actions = models_parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="show known models and cached sizes").set_defaults(
        handler=_cmd_models_list
    )
    fetch = actions.add_parser("fetch", help="download and verify models")
    fetch.add_argument("--dry-run", action="store_true", help="print the plan; no network")
    fetch.add_argument("names", nargs="*", metavar="NAME", help="models to fetch (default: all)")
    fetch.set_defaults(handler=_cmd_models_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    return int(args.handler(args))
