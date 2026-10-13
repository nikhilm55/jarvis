"""No-wake-word windows: listen after a bare 'Jarvis' (FR-ACT-07), reply to ask (FR-ACT-08)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

__all__ = ["WindowKind", "Windows"]

WindowKind = Literal["listen", "reply"]


class Windows:
    """Manages the single active no-wake-word window (listen or reply)."""

    def __init__(self) -> None:
        """Initialise the window manager with no open window."""
        self._kind: WindowKind | None = None
        self._timer: asyncio.Task[None] | None = None
        self._answer: asyncio.Future[str] | None = None

    @property
    def kind(self) -> WindowKind | None:
        """Return the kind of the currently open window, or None."""
        return self._kind

    def open_listen(
        self,
        seconds: float,
        on_timeout: Callable[[], Awaitable[None]],
    ) -> None:
        """Open a listen window that expires after the given seconds."""
        self.close()
        self._kind = "listen"
        loop = asyncio.get_running_loop()
        self._timer = loop.create_task(self._expire_listen(seconds, on_timeout))

    async def _expire_listen(
        self,
        seconds: float,
        on_timeout: Callable[[], Awaitable[None]],
    ) -> None:
        """Wait for the listen window to expire and invoke the timeout callback."""
        await asyncio.sleep(seconds)
        self._kind = None
        self._timer = None
        await on_timeout()

    async def ask(self, seconds: float) -> str:
        """Open a reply window and await the answer or a timeout."""
        self.close()
        self._kind = "reply"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._answer = future
        self._timer = loop.create_task(self._expire_reply(seconds, future))
        try:
            return await future
        finally:
            self._finish(future)

    async def _expire_reply(self, seconds: float, future: asyncio.Future[str]) -> None:
        """Wait for the reply window to expire and resolve with timeout."""
        await asyncio.sleep(seconds)
        if not future.done():
            future.set_result("timeout")

    def _finish(self, future: asyncio.Future[str]) -> None:
        """Clean up the reply window state if it has not been replaced."""
        if self._answer is future:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = None
            self._answer = None
            self._kind = None

    def take_listen(self) -> bool:
        """Consume the listen window if open, returning True on success."""
        if self._kind == "listen":
            if self._timer is not None:
                self._timer.cancel()
            self._kind = None
            self._timer = None
            return True
        return False

    def offer_answer(self, text: str) -> bool:
        """Deliver an answer to the open reply window, returning True on success."""
        if self._kind == "reply" and self._answer is not None and not self._answer.done():
            self._answer.set_result(text)
            self._kind = None
            if self._timer is not None:
                self._timer.cancel()
            self._timer = None
            self._answer = None
            return True
        return False

    def close(self) -> None:
        """Close the current window, resolving any pending reply with timeout."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._answer is not None and not self._answer.done():
            self._answer.set_result("timeout")
        self._answer = None
        self._kind = None
