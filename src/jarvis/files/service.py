"""The file tools as jarvisd runs them (FR-PC-08, §6.5): blocking work off the event loop,
undo entries for trash, move and rename (R90), and a summary line the brain can say."""

import asyncio
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from jarvis.files import ops
from jarvis.files.search import search
from jarvis.undo import UndoLog

__all__ = ["FilesService"]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _where(paths: Sequence[Path]) -> str:
    parents = {p.parent.name or str(p.parent) for p in paths}
    return parents.pop() if len(parents) == 1 else "several folders"


class FilesService:
    """Runs the file tools for one user; `undo` collects what can be reversed."""

    def __init__(
        self,
        undo: UndoLog,
        *,
        trash: ops.Trash | None = None,
        home: Path | None = None,
        launch: Callable[[list[str]], object] | None = None,
    ) -> None:
        """`trash`, `home` and `launch` are seams (tests point them at tmp_path)."""
        self._undo = undo
        self._trash = trash or ops.Trash()
        self._home = home
        self._launch = launch or _detached

    async def search_files(
        self, query: str, folder: str = "~", when: str | None = None, kind: str | None = None
    ) -> dict[str, object]:
        """Find files by name under `folder`, newest first."""
        root = ops.resolve(folder, self._home)
        hits = await asyncio.to_thread(search, query, root, when=when, kind=kind)
        found = [
            {"path": h.path, "name": h.name, "modified": h.modified, "size": h.size} for h in hits
        ]
        return {"count": len(found), "hits": found}

    async def open_file(self, path: str) -> dict[str, object]:
        """Open a file or folder with its default app."""
        target = await asyncio.to_thread(ops.resolve, path, self._home)
        if not target.exists():
            raise ops.FileError("NOT_FOUND", f"there is no {target.name}")
        self._launch(["gio", "open", str(target)])
        return {"opened": str(target)}

    async def reveal(self, path: str) -> dict[str, object]:
        """Show a file in the file manager (its folder, with the file selected when it can)."""
        target = ops.resolve(path, self._home)
        if not target.exists():
            raise ops.FileError("NOT_FOUND", f"there is no {target.name}")
        uri = target.as_uri()
        self._launch(
            [
                "gdbus", "call", "--session",
                "--dest", "org.freedesktop.FileManager1",
                "--object-path", "/org/freedesktop/FileManager1",
                "--method", "org.freedesktop.FileManager1.ShowItems", f"['{uri}']", "",
            ]
        )  # fmt: skip
        return {"revealed": str(target)}

    async def trash(self, paths: list[str], contents: bool = False) -> dict[str, object]:
        """Move to the trash (§6.5: 'delete' means this); undoable."""
        items = await asyncio.to_thread(self._trash.put, paths, contents=contents, home=self._home)
        where = _where([item.original for item in items]) if items else "there"
        summary = f"Moved {_plural(len(items), 'item')} from {where} to the trash."
        undoable = [item for item in items if item.trashed is not None]
        if undoable:
            summary += " Say 'undo' to bring them back."

            async def restore() -> str:
                back = await asyncio.to_thread(self._trash.restore, undoable)
                return f"Put {_plural(back, 'item')} back in {where}."

            self._undo.push(f"trashed {_plural(len(undoable), 'item')}", restore)
        return {"count": len(items), "undoable": len(undoable), "summary": summary}

    async def delete_permanently(self, paths: list[str]) -> dict[str, object]:
        """Delete for good (T3: the guardrail asked first); never undoable."""
        count = await asyncio.to_thread(ops.delete_forever, paths, self._home)
        return {"count": count, "summary": f"Permanently deleted {_plural(count, 'item')}."}

    async def move(self, paths: list[str], dest: str) -> dict[str, object]:
        """Move into a folder; undoable."""
        pairs = await asyncio.to_thread(ops.move_into, paths, dest, self._home)
        self._push_moves(pairs, "moved")
        where = pairs[0][1].parent.name if pairs else dest
        return {"count": len(pairs), "summary": f"Moved {_plural(len(pairs), 'item')} to {where}."}

    async def rename(self, path: str, name: str) -> dict[str, object]:
        """Rename in place; undoable."""
        src, dst = await asyncio.to_thread(ops.rename_to, path, name, self._home)
        self._push_moves([(src, dst)], "renamed")
        return {"renamed": str(dst), "summary": f"Renamed {src.name} to {dst.name}."}

    async def copy(self, paths: list[str], dest: str) -> dict[str, object]:
        """Copy into a folder."""
        made = await asyncio.to_thread(ops.copy_into, paths, dest, self._home)
        where = made[0].parent.name if made else dest
        return {"count": len(made), "summary": f"Copied {_plural(len(made), 'item')} to {where}."}

    async def zip(self, paths: list[str], dest: str) -> dict[str, object]:
        """Make a new zip archive."""
        archive = await asyncio.to_thread(ops.zip_into, paths, dest, self._home)
        return {"archive": str(archive), "summary": f"Made {archive.name}."}

    def _push_moves(self, pairs: list[tuple[Path, Path]], verb: str) -> None:
        if not pairs:
            return

        async def back() -> str:
            moved = await asyncio.to_thread(ops.undo_moves, pairs)
            where = "it was" if moved == 1 else "they were"
            return f"Put {_plural(moved, 'item')} back where {where}."

        self._undo.push(f"{verb} {_plural(len(pairs), 'item')}", back)


def _detached(argv: list[str]) -> object:
    if shutil.which(argv[0]) is None:
        raise ops.FileError("UNSUPPORTED_ON_PLATFORM", f"{argv[0]} is not installed")
    return subprocess.Popen(  # noqa: S603 - fixed argv, no shell; the app outlives the call
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
