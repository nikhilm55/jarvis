"""File operations for the file tools (FR-PC-08): trash with restore, move, copy, rename, zip.

Paths are the user's: `~` expands, and a relative path is under the home folder (as the policy
reads them). Nothing is overwritten: a name already taken at the destination is an error.
Trash follows the freedesktop.org spec (files/ plus info/*.trashinfo), so a trashed item can be
put back exactly where it was; across file systems it falls back to `gio trash`, which the
desktop can restore but Jarvis cannot undo.
"""

import contextlib
import datetime
import os
import shutil
import subprocess
import urllib.parse
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FileError",
    "Trash",
    "Trashed",
    "copy_into",
    "delete_forever",
    "move_into",
    "rename_to",
    "resolve",
    "zip_into",
]


class FileError(Exception):
    """A file step that cannot be done; `code` is an Appendix B code."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code and message."""
        super().__init__(message)
        self.code = code
        self.message = message


def resolve(path: str, home: Path | None = None) -> Path:
    """`~`, `$HOME` and relative paths (against home), made absolute; links are not followed."""
    if not isinstance(path, str) or not path.strip():
        raise FileError("NOT_FOUND", "a file path is needed")
    base = home or Path.home()
    text = path.strip()
    if text == "~" or text.startswith(("~/", "$HOME")):
        text = str(base) + text.removeprefix("$HOME").removeprefix("~")
    return Path(os.path.normpath(base / text))


def _existing(path: str, home: Path | None) -> Path:
    resolved = resolve(path, home)
    if not resolved.exists() and not resolved.is_symlink():
        raise FileError("NOT_FOUND", f"there is no {resolved.name or resolved}")
    return resolved


def _free(target: Path) -> Path:
    if target.exists() or target.is_symlink():
        raise FileError("INTERNAL", f"{target.name} already exists in {target.parent}")
    return target


@dataclass(frozen=True)
class Trashed:
    """One item moved to the trash: where it is now, and where it came from."""

    trashed: Path | None  # None: trashed by gio across file systems (no undo)
    original: Path


class Trash:
    """The user's home trash (freedesktop.org), or one given for tests."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        now: Callable[[], datetime.datetime] = datetime.datetime.now,
        run: Callable[..., object] = subprocess.run,
    ) -> None:
        """`root` is the trash directory (default `$XDG_DATA_HOME/Trash`)."""
        data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        self.root = root or Path(data_home) / "Trash"
        self._now = now
        self._run = run

    def put(
        self, paths: Sequence[str], *, contents: bool = False, home: Path | None = None
    ) -> list[Trashed]:
        """Move `paths` (with `contents`: everything inside each folder) to the trash."""
        items: list[Path] = []
        for path in paths:
            found = _existing(path, home)
            if contents:
                if not found.is_dir():
                    raise FileError("NOT_FOUND", f"{found.name} is not a folder")
                items += sorted(found.iterdir())
            else:
                items.append(found)
        return [self._one(item) for item in items]

    def _one(self, item: Path) -> Trashed:
        files, info = self.root / "files", self.root / "info"
        files.mkdir(parents=True, exist_ok=True, mode=0o700)
        info.mkdir(parents=True, exist_ok=True, mode=0o700)
        name, record = self._reserve(info, item)
        try:
            os.rename(item, files / name)
        except OSError as error:
            record.unlink(missing_ok=True)
            if error.errno == 18:  # EXDEV: another file system; the desktop's trash takes it
                self._run(["gio", "trash", str(item)], check=True, timeout=30)
                return Trashed(None, item)
            raise FileError(
                "PERMISSION_DENIED", f"cannot move {item.name}: {error.strerror}"
            ) from error
        return Trashed(files / name, item)

    def _reserve(self, info: Path, item: Path) -> tuple[str, Path]:
        """A free trash name, claimed by creating its .trashinfo (O_EXCL), and that record."""
        stem = item.name
        for n in range(1, 10000):
            name = stem if n == 1 else f"{stem}.{n}"
            record = info / f"{name}.trashinfo"
            try:
                fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            stamp = self._now().strftime("%Y-%m-%dT%H:%M:%S")
            body = f"[Trash Info]\nPath={urllib.parse.quote(str(item))}\nDeletionDate={stamp}\n"
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(body)
            return name, record
        raise FileError("INTERNAL", f"the trash already holds too many items named {stem}")

    def restore(self, items: Sequence[Trashed]) -> int:
        """Put trashed items back where they were; returns how many came back."""
        back = 0
        for item in items:
            if item.trashed is None or not (item.trashed.exists() or item.trashed.is_symlink()):
                continue
            if item.original.exists() or item.original.is_symlink():
                continue  # something new took its place: never overwrite it
            item.original.parent.mkdir(parents=True, exist_ok=True)
            os.rename(item.trashed, item.original)
            (self.root / "info" / f"{item.trashed.name}.trashinfo").unlink(missing_ok=True)
            back += 1
        return back


def move_into(paths: Sequence[str], dest: str, home: Path | None = None) -> list[tuple[Path, Path]]:
    """Move each path into the folder `dest`; returns (from, to) pairs, for undo."""
    folder = _existing(dest, home)
    if not folder.is_dir():
        raise FileError("NOT_FOUND", f"{folder.name} is not a folder")
    pairs = [(src, _free(folder / src.name)) for src in (_existing(p, home) for p in paths)]
    done: list[tuple[Path, Path]] = []
    for src, dst in pairs:
        shutil.move(src, dst)
        done.append((src, dst))
    return done


def rename_to(path: str, name: str, home: Path | None = None) -> tuple[Path, Path]:
    """Rename a file or folder in place; `name` is a plain name, not a path."""
    if not name.strip() or "/" in name or name in (".", ".."):
        raise FileError("INTERNAL", "the new name must be a plain file name")
    src = _existing(path, home)
    dst = _free(src.with_name(name.strip()))
    os.rename(src, dst)
    return src, dst


def copy_into(paths: Sequence[str], dest: str, home: Path | None = None) -> list[Path]:
    """Copy each path (folders whole) into the folder `dest`; returns the new paths."""
    folder = _existing(dest, home)
    if not folder.is_dir():
        raise FileError("NOT_FOUND", f"{folder.name} is not a folder")
    pairs = [(src, _free(folder / src.name)) for src in (_existing(p, home) for p in paths)]
    for src, dst in pairs:
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
    return [dst for _, dst in pairs]


def delete_forever(paths: Sequence[str], home: Path | None = None) -> int:
    """Delete permanently (T3, never undoable); a link is removed, never what it points to."""
    targets = [_existing(p, home) for p in paths]
    for target in targets:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    return len(targets)


def zip_into(paths: Sequence[str], archive: str, home: Path | None = None) -> Path:
    """Zip files and folders into a new archive; names inside are relative to each item."""
    target = _free(resolve(archive if archive.endswith(".zip") else archive + ".zip", home))
    sources = [_existing(p, home) for p in paths]
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as out:
        for src in sources:
            if src.is_dir():
                for file in sorted(src.rglob("*")):
                    if file.is_file() and not file.is_symlink():
                        out.write(file, Path(src.name) / file.relative_to(src))
            else:
                out.write(src, src.name)
    return target


def undo_moves(pairs: Sequence[tuple[Path, Path]]) -> int:
    """Move each (from, to) back to `from`, newest first; skip any whose `from` is taken."""
    back = 0
    for src, dst in reversed(pairs):
        if (dst.exists() or dst.is_symlink()) and not src.exists():
            with contextlib.suppress(OSError):
                shutil.move(dst, src)
                back += 1
    return back
