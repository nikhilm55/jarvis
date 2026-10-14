"""Where Jarvis keeps its files. `JARVIS_HOME` relocates everything (tests, portable installs).

The four functions only compute paths and never touch the disk; call `ensure()` on a path
at the moment something is about to be written there.
"""

import os
from pathlib import Path

import platformdirs

APP = "jarvis"


def _home() -> Path | None:
    value = os.environ.get("JARVIS_HOME")
    return Path(value) if value else None


def data_dir() -> Path:
    home = _home()
    return home / "data" if home else platformdirs.user_data_path(APP, appauthor=False)


def config_dir() -> Path:
    home = _home()
    return home / "config" if home else platformdirs.user_config_path(APP, appauthor=False)


def cache_dir() -> Path:
    home = _home()
    return home / "cache" if home else platformdirs.user_cache_path(APP, appauthor=False)


def runtime_dir() -> Path:
    home = _home()
    return home / "run" if home else platformdirs.user_runtime_path(APP, appauthor=False)


def ensure(path: Path) -> Path:
    """Create `path` (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
