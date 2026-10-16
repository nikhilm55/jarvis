"""Import modules from tools/wakeword (a script directory, not a package) without leaking them."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

TOOLS = Path(__file__).resolve().parent.parent / "tools" / "wakeword"


@contextmanager
def wakeword_modules(*names: str) -> Iterator[list[ModuleType]]:
    """Yield the named modules; on exit remove them and their siblings from sys.modules."""
    before = set(sys.modules)
    sys.path.insert(0, str(TOOLS))
    try:
        yield [importlib.import_module(name) for name in names]
    finally:
        sys.path.remove(str(TOOLS))
        for name in set(sys.modules) - before:
            if str(getattr(sys.modules[name], "__file__", "")).startswith(str(TOOLS)):
                del sys.modules[name]
