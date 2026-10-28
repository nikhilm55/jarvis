"""search_files (FR-PC-08): fd, then locate, then find, then a capped walk; when/type filters.

The query matches file names, case-insensitively, as words in any order ("invoice pdf" finds
"Invoice-2026.pdf"). `when` keeps files changed in a window (today, yesterday, this week, last
week, this month); `kind` keeps a family of types (document, pdf, image, …). Hidden folders are
skipped. At most `limit` hits come back, newest first.
"""

import datetime
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = ["KINDS", "WHENS", "FileHit", "search"]

KINDS: dict[str, frozenset[str]] = {
    "document": frozenset({".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pdf"}),
    "pdf": frozenset({".pdf"}),
    "spreadsheet": frozenset({".xls", ".xlsx", ".ods", ".csv"}),
    "presentation": frozenset({".ppt", ".pptx", ".odp", ".key"}),
    "image": frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic", ".bmp"}),
    "video": frozenset({".mp4", ".mkv", ".mov", ".webm", ".avi"}),
    "audio": frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a"}),
    "archive": frozenset({".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".xz"}),
}
WHENS = ("today", "yesterday", "this week", "last week", "this month")
_WALK_CAP = 50_000  # entries the Python fallback looks at before giving up


@dataclass(frozen=True)
class FileHit:
    """One file found."""

    path: str
    name: str
    modified: str  # ISO date and time
    size: int
    folder: bool


Run = Callable[..., subprocess.CompletedProcess[str]]


def _window(when: str, now: datetime.datetime) -> tuple[float, float]:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - datetime.timedelta(days=day.weekday())
    spans = {
        "today": (day, now),
        "yesterday": (day - datetime.timedelta(days=1), day),
        "this week": (week, now),
        "last week": (week - datetime.timedelta(days=7), week),
        "this month": (day.replace(day=1), now),
    }
    start, end = spans[when]
    return start.timestamp(), end.timestamp() + 1


def _words(query: str) -> list[str]:
    return [w for w in re.split(r"[\s_.\-]+", query.lower()) if w]


def _matches(name: str, words: list[str]) -> bool:
    low = name.lower()
    return all(word in low for word in words)


def _candidates(root: Path, words: list[str], run: Run) -> Iterable[str]:
    """Paths whose names may match, from the fastest tool there is."""
    pattern = max(words, key=len) if words else ""
    fd = shutil.which("fd") or shutil.which("fdfind")
    if fd:
        done = run(
            [fd, "--absolute-path", "--ignore-case", pattern, str(root)],
            capture_output=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        if done.returncode == 0:
            return done.stdout.splitlines()
    locate = shutil.which("plocate") or shutil.which("locate")
    if locate:
        done = run(
            [locate, "-i", "-l", "5000", pattern],
            capture_output=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        if done.returncode == 0:
            return [p for p in done.stdout.splitlines() if p.startswith(str(root) + os.sep)]
    if shutil.which("find"):
        done = run(
            ["find", str(root), "-not", "-path", "*/.*", "-iname", f"*{pattern}*"],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if done.returncode in (0, 1):
            return done.stdout.splitlines()
    return _walk(root)


def _walk(root: Path) -> Iterable[str]:
    seen = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in dirs + names:
            seen += 1
            if seen > _WALK_CAP:
                return
            yield os.path.join(folder, name)


def search(  # noqa: PLR0913 - the query, its filters, and test seams
    query: str,
    root: Path,
    *,
    when: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    now: Callable[[], datetime.datetime] = datetime.datetime.now,
    run: Run = subprocess.run,
) -> list[FileHit]:
    """Files under `root` whose names hold every word of `query`, newest first."""
    if when is not None and when not in WHENS:
        raise ValueError(f"when must be one of {', '.join(WHENS)}")
    if kind is not None and kind not in KINDS and kind != "folder":
        raise ValueError(f"kind must be one of {', '.join([*KINDS, 'folder'])}")
    words = _words(query)
    window = _window(when, now()) if when else None
    hits: list[tuple[float, str, FileHit]] = []
    for raw in _candidates(root, words, run):
        path = Path(raw)
        if not path.is_relative_to(root) or any(
            part.startswith(".") for part in path.relative_to(root).parts
        ):
            continue  # outside the folder asked about, or hidden
        if not _matches(path.name, words):
            continue
        try:
            info = path.lstat()
        except OSError:
            continue
        folder = path.is_dir()
        if kind == "folder" and not folder:
            continue
        if kind in KINDS and (folder or path.suffix.lower() not in KINDS[kind]):
            continue
        if window and not window[0] <= info.st_mtime < window[1]:
            continue
        stamp = datetime.datetime.fromtimestamp(info.st_mtime).isoformat(timespec="minutes")
        # Raw epoch seconds (not the minute-resolution stamp) so files a second
        # apart order deterministically on every filesystem (CI tie bug, s1.1).
        hits.append(
            (info.st_mtime, str(path), FileHit(str(path), path.name, stamp, info.st_size, folder))
        )
    hits.sort(key=lambda hit: (hit[0], hit[1]), reverse=True)
    return [entry[2] for entry in hits]
    return hits[:limit]
