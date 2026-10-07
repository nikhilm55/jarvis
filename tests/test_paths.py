from pathlib import Path

import pytest

from jarvis import paths


def test_should_nest_each_folder_under_jarvis_home_when_it_is_set(jarvis_home: Path) -> None:
    assert paths.data_dir() == jarvis_home / "data"
    assert paths.config_dir() == jarvis_home / "config"
    assert paths.cache_dir() == jarvis_home / "cache"
    assert paths.runtime_dir() == jarvis_home / "run"


def test_should_use_platform_folders_when_jarvis_home_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_HOME")
    for folder in (paths.data_dir(), paths.config_dir(), paths.cache_dir(), paths.runtime_dir()):
        assert "jarvis" in folder.parts or "jarvis" in folder.name.lower()


def test_should_create_nothing_until_ensure_is_called(jarvis_home: Path) -> None:
    folder = paths.data_dir()
    assert not jarvis_home.exists()
    assert paths.ensure(folder / "logs") == folder / "logs"
    assert (folder / "logs").is_dir()
