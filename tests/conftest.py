from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def jarvis_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every Jarvis path at a throwaway folder — tests never touch real user data."""
    home = tmp_path / "jarvis-home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    return home
