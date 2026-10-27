"""The kill-switch hotkey `Ctrl+Alt+Esc` (FR-SAFE-04, R89/R103), grabbed on X11.

A daemon thread with its own X connection grabs the key on the root window, in every
combination of Caps Lock and Num Lock, and calls `on_press` from that thread for each press.
It lives in jarvisd, not the desktop worker, so a worker restart never drops the grab (R103).
A grab that fails (another app owns the combination, no X display) is logged; the voice and
HUD paths still work.
"""

import os
import select
import threading
from collections.abc import Callable
from typing import Any

from jarvis.log import get_logger

__all__ = ["Hotkey"]

logger = get_logger("hotkey")
_POLL_S = 0.2


class Hotkey:
    """Calls `on_press` (from its own thread) each time `Ctrl+Alt+Esc` is pressed."""

    def __init__(self, on_press: Callable[[], None], *, display: Any = None) -> None:
        """`display` is a python-xlib Display for tests; None opens the user's at start."""
        self._on_press = on_press
        self._display = display
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Grab the key and start listening; False (logged) when it cannot be grabbed."""
        try:
            display = self._display or self._open()
            if display is None:
                return False
            self._grab(display)
        except Exception:
            logger.warning("the Ctrl+Alt+Esc kill switch is unavailable", exc_info=True)
            return False
        self._display = display
        self._thread = threading.Thread(target=self._listen, name="jarvis-hotkey", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop listening and close the X connection."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                logger.debug("closing the hotkey display failed", exc_info=True)

    @staticmethod
    def _open() -> Any:
        if not os.environ.get("DISPLAY"):
            logger.info("no X display: the Ctrl+Alt+Esc kill switch is off")
            return None
        from Xlib import display  # noqa: PLC0415 - X11 only, and only when there is a display

        return display.Display()

    def _grab(self, display: Any) -> None:
        from Xlib import XK, X, error  # noqa: PLC0415

        root = display.screen().root
        keycode = display.keysym_to_keycode(XK.string_to_keysym("Escape"))
        catch = error.CatchError(error.BadAccess)
        for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):  # Caps, Num Lock
            modifiers = X.ControlMask | X.Mod1Mask | extra
            root.grab_key(keycode, modifiers, True, X.GrabModeAsync, X.GrabModeAsync, onerror=catch)
        display.sync()
        if catch.get_error() is not None:
            raise RuntimeError("Ctrl+Alt+Esc is grabbed by another application")
        self._keycode = keycode

    def _listen(self) -> None:
        from Xlib import X  # noqa: PLC0415

        display = self._display
        while not self._stop.is_set():
            try:
                if not display.pending_events():
                    select.select([display.fileno()], [], [], _POLL_S)
                    continue
                event = display.next_event()
            except Exception:
                if not self._stop.is_set():
                    logger.warning("the hotkey listener stopped", exc_info=True)
                return
            if event.type == X.KeyPress and event.detail == self._keycode:
                try:
                    self._on_press()
                except Exception:
                    logger.exception("the kill switch hotkey handler failed")
