from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from tests.wakeword_loader import wakeword_modules


@pytest.fixture
def fetch() -> Iterator[ModuleType]:
    with wakeword_modules("fetch") as (module,):
        yield module


def test_should_stop_and_delete_the_partial_file_when_a_download_passes_its_allowance(
    fetch: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "big.bin"
    source.write_bytes(b"x" * (3 << 20))
    out = tmp_path / "out" / "big.bin"
    with pytest.raises(fetch.OverBudget):
        fetch._download(source.as_uri(), out, 1 << 20)
    assert not out.exists()
    assert not list(out.parent.glob("*.part"))


def test_should_download_when_the_file_fits_its_allowance(
    fetch: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "small.bin"
    source.write_bytes(b"abc")
    n, _ = fetch._download(source.as_uri(), tmp_path / "small-copy.bin", 10)
    assert n == 3
    assert (tmp_path / "small-copy.bin").read_bytes() == b"abc"


def test_should_not_leave_the_target_behind_when_an_unpack_is_interrupted(
    fetch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ch01.wav", b"data")
    monkeypatch.setattr(
        zipfile.ZipFile, "extractall", lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    into = tmp_path / "noise" / "ROOM"
    with pytest.raises(KeyboardInterrupt):
        fetch._unpack(archive, "zip", into)
    assert not into.exists()
    assert not list(into.parent.glob("*.unpacking"))
    monkeypatch.undo()
    fetch._unpack(archive, "zip", into)
    assert (into / "ch01.wav").read_bytes() == b"data"
