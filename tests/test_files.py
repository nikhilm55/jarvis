"""File tools (FR-PC-08), trash with undo (R90, §6.5), search, and walks_tree scopes."""

import asyncio
import datetime
import os
import subprocess
import urllib.parse
import zipfile
from pathlib import Path

import pytest

from jarvis.config import PolicySettings
from jarvis.files import ops
from jarvis.files.search import search
from jarvis.files.service import FilesService
from jarvis.policy import ToolCall, TurnContext
from jarvis.policy.decide import decide
from jarvis.policy.lists import path_scopes
from jarvis.undo import NOTHING_TO_UNDO, UndoLog


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / "Downloads").mkdir(parents=True)
    for name in ("a.txt", "b.pdf", "c"):
        (root / "Downloads" / name).write_text(name, encoding="utf-8")
    (root / "Documents").mkdir()
    return root


def service(home: Path, undo: UndoLog | None = None) -> tuple[FilesService, UndoLog, ops.Trash]:
    log = undo or UndoLog()
    trash = ops.Trash(home.parent / "Trash")
    return FilesService(log, trash=trash, home=home, launch=lambda argv: None), log, trash


# --- §6.5: delete means the trash, and undo brings it back ------------------------------------


def test_should_trash_everything_in_a_folder_and_say_how_to_undo(home: Path) -> None:
    files, log, trash = service(home)
    result = asyncio.run(files.trash(["~/Downloads"], contents=True))
    assert result["count"] == 3
    assert result["summary"] == (
        "Moved 3 items from Downloads to the trash. Say 'undo' to bring them back."
    )
    assert list((home / "Downloads").iterdir()) == []
    assert sorted(p.name for p in (trash.root / "files").iterdir()) == ["a.txt", "b.pdf", "c"]
    info = (trash.root / "info" / "a.txt.trashinfo").read_text(encoding="utf-8")
    assert f"Path={urllib.parse.quote(str(home / 'Downloads' / 'a.txt'))}" in info
    assert asyncio.run(log.revert_newest()) == "Put 3 items back in Downloads."
    assert sorted(p.name for p in (home / "Downloads").iterdir()) == ["a.txt", "b.pdf", "c"]
    assert list((trash.root / "info").iterdir()) == []


def test_should_keep_two_trashed_items_with_one_name_apart(home: Path) -> None:
    files, _, trash = service(home)
    asyncio.run(files.trash(["~/Downloads/a.txt"]))
    (home / "Downloads" / "a.txt").write_text("again", encoding="utf-8")
    asyncio.run(files.trash(["~/Downloads/a.txt"]))
    assert sorted(p.name for p in (trash.root / "files").iterdir()) == ["a.txt", "a.txt.2"]


def test_should_never_overwrite_on_undo(home: Path) -> None:
    files, log, _ = service(home)
    asyncio.run(files.trash(["~/Downloads/a.txt"]))
    (home / "Downloads" / "a.txt").write_text("new", encoding="utf-8")
    assert asyncio.run(log.revert_newest()) == "Put 0 items back in Downloads."
    assert (home / "Downloads" / "a.txt").read_text(encoding="utf-8") == "new"


def test_should_report_a_missing_file(home: Path) -> None:
    files, _, _ = service(home)
    with pytest.raises(ops.FileError) as caught:
        asyncio.run(files.trash(["~/Downloads/nope"]))
    assert caught.value.code == "NOT_FOUND"


def test_should_fall_back_to_gio_across_file_systems(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[list[str]] = []

    def cross_device(src: object, dst: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    trash = ops.Trash(home.parent / "Trash", run=lambda argv, **kw: ran.append(argv))
    monkeypatch.setattr("jarvis.files.ops.os.rename", cross_device)
    [item] = trash.put(["~/Downloads/a.txt"], home=home)
    assert item.trashed is None and ran == [["gio", "trash", str(home / "Downloads" / "a.txt")]]


# --- move, rename, copy, zip, delete ------------------------------------------------------------


def test_should_move_and_undo_the_move(home: Path) -> None:
    files, log, _ = service(home)
    result = asyncio.run(files.move(["~/Downloads/b.pdf"], "~/Documents"))
    assert result["summary"] == "Moved 1 item to Documents."
    assert (home / "Documents" / "b.pdf").exists()
    assert asyncio.run(log.revert_newest()) == "Put 1 item back where it was."
    assert (home / "Downloads" / "b.pdf").exists()


def test_should_rename_and_refuse_a_path_as_the_new_name(home: Path) -> None:
    files, log, _ = service(home)
    asyncio.run(files.rename("~/Downloads/c", "c.txt"))
    assert (home / "Downloads" / "c.txt").exists()
    with pytest.raises(ops.FileError):
        asyncio.run(files.rename("~/Downloads/c.txt", "../escape"))
    asyncio.run(log.revert_newest())
    assert (home / "Downloads" / "c").exists()


def test_should_refuse_to_overwrite_on_move_or_copy(home: Path) -> None:
    files, _, _ = service(home)
    (home / "Documents" / "a.txt").write_text("keep", encoding="utf-8")
    for step in (files.move, files.copy):
        with pytest.raises(ops.FileError):
            asyncio.run(step(["~/Downloads/a.txt"], "~/Documents"))
    assert (home / "Documents" / "a.txt").read_text(encoding="utf-8") == "keep"


def test_should_copy_and_zip(home: Path) -> None:
    files, _, _ = service(home)
    asyncio.run(files.copy(["~/Downloads"], "~/Documents"))
    assert (home / "Documents" / "Downloads" / "a.txt").exists()
    result = asyncio.run(files.zip(["~/Downloads"], "~/Documents/backup"))
    with zipfile.ZipFile(home / "Documents" / "backup.zip") as archive:
        assert sorted(archive.namelist()) == ["Downloads/a.txt", "Downloads/b.pdf", "Downloads/c"]
    assert result["summary"] == "Made backup.zip."


def test_should_delete_a_link_never_its_target(home: Path) -> None:
    files, _, _ = service(home)
    os.symlink(home / "Documents", home / "Downloads" / "docs-link")
    (home / "Documents" / "keep.txt").write_text("keep", encoding="utf-8")
    asyncio.run(files.delete_permanently(["~/Downloads/docs-link"]))
    assert not (home / "Downloads" / "docs-link").exists()
    assert (home / "Documents" / "keep.txt").exists()


def test_should_resolve_paths_like_the_policy(home: Path) -> None:
    assert ops.resolve("~/Downloads/../Documents", home) == home / "Documents"
    assert ops.resolve("Downloads", home) == home / "Downloads"
    assert ops.resolve("$HOME/x", home) == home / "x"
    with pytest.raises(ops.FileError):
        ops.resolve("  ", home)


# --- search -------------------------------------------------------------------------------------


def _no_tools(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 2, "", "")  # every tool fails: the Python walk runs


def test_should_find_by_words_in_any_order_newest_first(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i, name in enumerate(["Invoice-2026.pdf", "invoice notes.txt", "other.pdf"]):
        path = home / "Documents" / name
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
    (home / "Documents" / ".hidden").mkdir()
    (home / "Documents" / ".hidden" / "invoice.pdf").write_text("x", encoding="utf-8")
    monkeypatch.setattr("jarvis.files.search.shutil.which", lambda name: None)
    hits = search("invoice", home, run=_no_tools)
    assert [h.name for h in hits] == ["invoice notes.txt", "Invoice-2026.pdf"]
    assert [h.name for h in search("pdf invoice", home, kind="pdf", run=_no_tools)] == [
        "Invoice-2026.pdf"
    ]


def test_should_filter_by_when(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.files.search.shutil.which", lambda name: None)
    now = datetime.datetime(2026, 10, 28, 12, 0)
    today = home / "Documents" / "today report.txt"
    old = home / "Documents" / "old report.txt"
    for path, when in ((today, now), (old, now - datetime.timedelta(days=40))):
        path.write_text("x", encoding="utf-8")
        os.utime(path, (when.timestamp(), when.timestamp()))
    hits = search("report", home, when="today", now=lambda: now, run=_no_tools)
    assert [h.name for h in hits] == ["today report.txt"]


def test_should_refuse_an_unknown_filter(home: Path) -> None:
    with pytest.raises(ValueError):
        search("x", home, when="someday")
    with pytest.raises(ValueError):
        search("x", home, kind="hologram")


# --- the undo log -------------------------------------------------------------------------------


def test_should_undo_the_newest_and_forget_after_an_hour() -> None:
    now = [0.0]
    log = UndoLog(clock=lambda: now[0])

    def revert(text: str):  # type: ignore[no-untyped-def]
        async def run() -> str:
            return text

        return run

    log.push("first", revert("undid first"))
    log.push("second", revert("undid second"))
    assert asyncio.run(log.revert_newest()) == "undid second"
    now[0] = 3601.0
    assert asyncio.run(log.revert_newest()) == NOTHING_TO_UNDO


# --- scopes: a tree walk needs the folders below ------------------------------------------------


def test_should_ask_for_the_folders_below_a_tree_walk() -> None:
    settings = PolicySettings()
    assert path_scopes({"paths": ["~"]}, "write", settings) == ()
    below = path_scopes({"paths": ["~"]}, "write", settings, below=True)
    assert "files.documents:write" in below and "files.downloads:write" in below


def test_should_scope_trash_of_home_to_every_consent_folder() -> None:
    decision = decide(
        ToolCall("files.trash", {"paths": ["~"]}, "brain"), "balanced", TurnContext("t")
    )
    assert {"files.documents:write", "files.desktop:write"} <= set(decision.scopes)
    permanent = decide(
        ToolCall("files.delete_permanently", {"paths": ["~/Downloads"]}, "brain"),
        "yolo",
        TurnContext("t"),
    )
    assert permanent.kind == "guardrail"  # T3 in YOLO: say 'confirm …' (§6.5)
