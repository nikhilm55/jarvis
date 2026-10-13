"""The children the orchestrator owns, and the order they are warmed up and closed (R30, R36)."""

import asyncio
import functools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from jarvis.audio import AudioSource
from jarvis.brain import BrainUnavailable
from jarvis.desktop.client import DesktopClient
from jarvis.log import get_logger
from jarvis.orchestrator.ports import (
    BrainPort,
    SegmenterPort,
    ServicePort,
    SpeakerPort,
    TranscriberPort,
)
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.voice import Voice

__all__ = ["Components", "close_components", "start_components"]

logger = get_logger(__name__)


@dataclass
class Components:
    """Everything the orchestrator drives; each child is injectable so tests use fakes."""

    source: AudioSource
    segmenter: SegmenterPort
    transcriber: TranscriberPort
    speaker: SpeakerPort
    voice: Voice
    desktop: DesktopClient
    brain: BrainPort | None = None
    services: Sequence[ServicePort] = ()  # e.g. the MCP server: up before the brain, down last
    trace: ToolTrace = field(default_factory=ToolTrace)


async def start_components(parts: Components) -> BrainUnavailable | None:
    """Start the services, then warm the transcriber and the brain in parallel.

    A transcriber failure propagates; an unavailable brain is returned so the caller can show it.
    """
    for service in parts.services:
        await service.start()
    _, brain_problem = await asyncio.gather(
        asyncio.to_thread(parts.transcriber.start), _start_brain(parts.brain)
    )
    return brain_problem


async def _start_brain(brain: BrainPort | None) -> BrainUnavailable | None:
    """Start the brain session; the fast path still works without it."""
    if brain is None:
        return None
    try:
        await brain.start()
    except BrainUnavailable as error:
        logger.warning("brain unavailable: %s", error)
        return error
    return None


async def close_components(parts: Components) -> None:
    """Close every child, brain first and services last; one failure never skips the rest."""
    closers: list[tuple[str, Callable[[], Awaitable[object]]]] = []
    if parts.brain is not None:
        closers.append(("brain", parts.brain.close))
    closers.append(("desktop", parts.desktop.close))
    closers.append(("speaker", functools.partial(asyncio.to_thread, parts.speaker.close)))
    closers.append(("transcriber", functools.partial(asyncio.to_thread, parts.transcriber.close)))
    closers.extend(("service", service.close) for service in reversed(parts.services))
    for name, close in closers:
        try:
            await close()
        except Exception:  # a failing child must not stop the others from closing
            logger.exception("closing %s failed", name)
