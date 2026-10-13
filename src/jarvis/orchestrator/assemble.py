"""Builds the real components for `jarvis run`; the only place that knows the concrete classes."""

import asyncio
import functools
import os
import subprocess
from pathlib import Path

from jarvis import models
from jarvis.audio import AudioSource, Endpointer, SileroVad
from jarvis.brain import ClaudeCodeBrain
from jarvis.config import Settings
from jarvis.desktop.client import DesktopClient
from jarvis.mcp import JarvisMcpServer
from jarvis.orchestrator.components import Components
from jarvis.orchestrator.ports import ServicePort
from jarvis.orchestrator.segmenter import Segmenter
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.voice import Voice
from jarvis.policy import Mode
from jarvis.stt import WhisperServer, find_server_bin
from jarvis.tts import Speaker
from jarvis.tts.engines import AudioEngine, Engine, default_engine
from jarvis.wake import WakeDetector

__all__ = ["build_components"]

# whisper-server in its own process group, so a Ctrl-C aimed at Jarvis does not hit it first
# and our own close() is what ends it (R30). Windows has no process groups to join.
_POPEN = (
    functools.partial(subprocess.Popen, start_new_session=True)
    if os.name == "posix"
    else subprocess.Popen
)


async def build_components(
    settings: Settings, source: AudioSource, *, mode: Mode, with_brain: bool
) -> Components:
    """Build every real child; heavy model loads run in threads (Kokoro is warmed here)."""
    timing = Timing.from_settings(settings)
    transcriber = await asyncio.to_thread(_transcriber, settings)
    engine = await asyncio.to_thread(_warm_engine, settings)
    speaker = Speaker(settings.tts, engine_factory=lambda: engine)
    voice = Voice(speaker, timing)
    segmenter = await asyncio.to_thread(_segmenter, settings, voice)
    desktop = DesktopClient()
    trace = ToolTrace()
    brain: ClaudeCodeBrain | None = None
    services: list[ServicePort] = []
    if with_brain:
        # The MCP server must exist before the brain, and the brain before any dispatch, so
        # the server's dispatch looks the brain up late (Task 10 hand-off).
        async def dispatch(name: str, args: dict[str, object]) -> object:
            if brain is None:
                raise RuntimeError("the brain is not running")
            return await brain.dispatch(name, args)

        mcp = JarvisMcpServer(trace.wrap(dispatch), lambda: mode)
        brain = ClaudeCodeBrain(settings, mcp, desktop)
        services.append(mcp)
    return Components(
        source=source,
        segmenter=segmenter,
        transcriber=transcriber,
        speaker=speaker,
        voice=voice,
        desktop=desktop,
        brain=brain,
        services=services,
        trace=trace,
    )


def _transcriber(settings: Settings) -> WhisperServer:
    """The warm whisper-server wrapper (started later, with the other warm-ups)."""
    model = models.ensure(f"whisper-{settings.stt.model}")
    server_bin = find_server_bin(settings.stt.server_bin)
    return WhisperServer(model, Path(server_bin), settings.stt.threads, popen=_POPEN)


def _warm_engine(settings: Settings) -> Engine:
    """Load the TTS engine now and run one silent synthesis so the first reply is fast."""
    engine = default_engine(settings.tts)
    if isinstance(engine, AudioEngine):
        engine.synthesize("Ready.")
    return engine


def _segmenter(settings: Settings, voice: Voice) -> Segmenter:
    """Endpointer plus wake detector, deaf while Jarvis speaks."""
    audio = settings.audio
    endpointer = Endpointer(SileroVad(), trailing_ms=audio.trailing_ms, cap_s=audio.cap_s)
    return Segmenter(endpointer, WakeDetector(settings.wake.model), voice.is_deaf)
