"""Keyboard and mouse input through XTest (FR-PC-03), for the desktop worker.

`type_into` (the type_text op) types key by key when every character is on the keyboard map
and the text is at most 200 characters; otherwise it pastes through the clipboard (xclip) and
puts the clipboard's text back afterwards. `press_combo` takes combos like "ctrl+shift+m".
`click_at` and `scroll_by` move the real pointer.
"""

import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from Xlib import XK, X
from Xlib.ext import xtest

__all__ = [
    "PASTE_ABOVE",
    "InputError",
    "click_at",
    "parse_combo",
    "press_combo",
    "scroll_by",
    "type_into",
]

PASTE_ABOVE = 200  # characters: longer text goes through the clipboard (plan 7a)
MAX_TEXT = 5000
_MODIFIERS = {
    "ctrl": "Control_L",
    "control": "Control_L",
    "shift": "Shift_L",
    "alt": "Alt_L",
    "super": "Super_L",
    "win": "Super_L",
    "meta": "Super_L",
}
_KEY_NAMES = {
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "printscreen": "Print",
    "menu": "Menu",
    "plus": "plus",
    "minus": "minus",
}
_BUTTONS = {"left": 1, "middle": 2, "right": 3}
_SCROLL_BUTTONS = {(0, -1): 4, (0, 1): 5, (-1, 0): 6, (1, 0): 7}  # up, down, left, right
_KEY_DELAY_S = 0.004


class InputError(Exception):
    """An input step that cannot be done; `code` is an Appendix B code."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code and message."""
        super().__init__(message)
        self.code = code
        self.message = message


def parse_combo(combo: str) -> tuple[list[str], str]:
    """ "ctrl+shift+m" -> (["Control_L", "Shift_L"], "m"). Raises InputError if malformed."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+")]
    if not parts or any(not p for p in parts):
        raise InputError("INTERNAL", f"not a key combination: {combo!r}")
    *mods, key = parts
    unknown = [m for m in mods if m not in _MODIFIERS]
    if unknown:
        raise InputError("INTERNAL", f"unknown modifier {unknown[0]!r} in {combo!r}")
    if key in _KEY_NAMES:
        name = _KEY_NAMES[key]
    elif len(key) == 1 or (key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24):
        name = key.upper() if key.startswith("f") and len(key) > 1 else key
    else:
        raise InputError("INTERNAL", f"unknown key {key!r} in {combo!r}")
    return [_MODIFIERS[m] for m in mods], name


def _keycode(disp: Any, name: str) -> int:
    keysym = XK.string_to_keysym(name)
    code = disp.keysym_to_keycode(keysym) if keysym else 0
    if not code:
        raise InputError("UNSUPPORTED_ON_PLATFORM", f"no key for {name!r} on this keyboard")
    return int(code)


def _tap(disp: Any, code: int, *, shift: int = 0) -> None:
    if shift:
        xtest.fake_input(disp, X.KeyPress, shift)
    xtest.fake_input(disp, X.KeyPress, code)
    xtest.fake_input(disp, X.KeyRelease, code)
    if shift:
        xtest.fake_input(disp, X.KeyRelease, shift)
    disp.sync()


def press_combo(disp: Any, combo: str) -> dict[str, object]:
    """Press a combination: modifiers down in order, the key, then modifiers up in reverse."""
    mods, key = parse_combo(combo)
    codes = [_keycode(disp, m) for m in mods]
    key_code = _keycode(disp, key)
    for code in codes:
        xtest.fake_input(disp, X.KeyPress, code)
    xtest.fake_input(disp, X.KeyPress, key_code)
    xtest.fake_input(disp, X.KeyRelease, key_code)
    for code in reversed(codes):
        xtest.fake_input(disp, X.KeyRelease, code)
    disp.sync()
    return {"pressed": combo}


def _char_keys(disp: Any, char: str) -> tuple[int, bool] | None:
    """(keycode, needs shift) for a character on the current keyboard map, else None."""
    keysym = XK.string_to_keysym(_CHAR_NAMES.get(char, char))
    if not keysym:
        keysym = ord(char) if ord(char) < 0x100 else 0x01000000 + ord(char)
    code = disp.keysym_to_keycode(keysym)
    if not code:
        return None
    if disp.keycode_to_keysym(code, 0) == keysym:
        return int(code), False
    if disp.keycode_to_keysym(code, 1) == keysym:
        return int(code), True
    return None


_CHAR_NAMES = {" ": "space", "\n": "Return", "\t": "Tab"}


def type_into(
    disp: Any,
    text: str,
    *,
    clipboard: "Clipboard | None" = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Type `text` into the focused field; long or unmapped text is pasted instead."""
    if not text or len(text) > MAX_TEXT:
        raise InputError("INTERNAL", f"text must be 1 to {MAX_TEXT} characters")
    found = [_char_keys(disp, ch) for ch in text] if len(text) <= PASTE_ABOVE else [None]
    keys = [k for k in found if k is not None]
    if len(keys) == len(text):
        shift = _keycode(disp, "Shift_L")
        for code, shifted in keys:
            _tap(disp, code, shift=shift if shifted else 0)
            sleep(_KEY_DELAY_S)
        return {"typed": len(text), "via": "keys"}
    board = clipboard or Clipboard()
    with board.holding(text):
        press_combo(disp, "ctrl+v")
        sleep(0.15)  # let the app read the clipboard before it is restored
    return {"typed": len(text), "via": "clipboard"}


def click_at(
    disp: Any, x: int, y: int, button: Literal["left", "middle", "right"] = "left", count: int = 1
) -> dict[str, object]:
    """Move the pointer to (x, y) on the root window and click `count` times."""
    screen = disp.screen()
    if not (0 <= x < screen.width_in_pixels and 0 <= y < screen.height_in_pixels):
        raise InputError("NOT_FOUND", f"({x}, {y}) is off the screen")
    if button not in _BUTTONS or not 1 <= count <= 3:
        raise InputError("INTERNAL", "button must be left, middle or right; count 1 to 3")
    xtest.fake_input(disp, X.MotionNotify, x=x, y=y)
    for _ in range(count):
        xtest.fake_input(disp, X.ButtonPress, _BUTTONS[button])
        xtest.fake_input(disp, X.ButtonRelease, _BUTTONS[button])
    disp.sync()
    return {"clicked": [x, y], "button": button, "count": count}


def scroll_by(disp: Any, dx: int, dy: int) -> dict[str, object]:
    """Scroll by whole notches: dy > 0 down, dy < 0 up, dx > 0 right, dx < 0 left."""
    if not (-50 <= dx <= 50 and -50 <= dy <= 50) or (dx == 0 and dy == 0):
        raise InputError("INTERNAL", "scroll by -50 to 50 notches, not both zero")
    for steps, direction in ((dy, (0, 1 if dy > 0 else -1)), (dx, (1 if dx > 0 else -1, 0))):
        for _ in range(abs(steps)):
            button = _SCROLL_BUTTONS[direction]
            xtest.fake_input(disp, X.ButtonPress, button)
            xtest.fake_input(disp, X.ButtonRelease, button)
    disp.sync()
    return {"scrolled": [dx, dy]}


class Clipboard:
    """The CLIPBOARD selection through xclip; its text is put back after a paste."""

    def __init__(self, run: Callable[..., Any] = subprocess.run) -> None:
        """`run` is subprocess.run (a seam for tests)."""
        self._run = run

    def _xclip(self, *args: str, data: str | None = None) -> str:
        if self._run is subprocess.run and shutil.which("xclip") is None:
            raise InputError(
                "UNSUPPORTED_ON_PLATFORM",
                "long text needs xclip to paste: install it (sudo apt install xclip)",
            )
        argv = ["xclip", "-selection", "clipboard", *args]
        if data is None:  # reading
            done = self._run(argv, capture_output=True, encoding="utf-8", timeout=5, check=False)
            return str(done.stdout or "") if done.returncode == 0 else ""
        # Writing: xclip forks a child that keeps serving the selection, so its output is not
        # captured (a captured pipe would stay open until the timeout).
        self._run(
            argv,
            input=data,
            encoding="utf-8",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return ""

    @contextmanager
    def holding(self, text: str) -> Iterator[None]:
        """Put `text` on the clipboard for the block, then restore what was there (text only)."""
        before = self._xclip("-o")
        self._xclip("-i", data=text)
        try:
            yield
        finally:
            self._xclip("-i", data=before)
