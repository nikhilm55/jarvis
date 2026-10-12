"""Index freedesktop .desktop launcher files and find an app by a spoken query."""

import configparser
import os
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppEntry:
    """A single application launcher entry parsed from a .desktop file."""

    desktop_id: str
    name: str
    generic_name: str
    keywords: tuple[str, ...]
    exec_line: str
    startup_wm_class: str
    path: Path

    @property
    def exec_name(self) -> str:
        """Return the basename of the program in exec_line, or "" on failure."""
        try:
            tokens = shlex.split(self.exec_line)
        except ValueError:
            return ""
        idx = 0
        if idx < len(tokens) and tokens[idx] == "env":
            idx += 1
            while idx < len(tokens) and "=" in tokens[idx]:
                idx += 1
        if idx >= len(tokens):
            return ""
        return Path(tokens[idx]).name


@dataclass(frozen=True)
class Ambiguous:
    """Multiple candidate entries matched the query equally well."""

    candidates: tuple[AppEntry, ...]


def _xdg_data_home() -> Path:
    """Return the XDG data home directory, defaulting to ~/.local/share."""
    raw = os.environ.get("XDG_DATA_HOME", "")
    if not raw:
        return Path.home() / ".local" / "share"
    return Path(raw)


def _xdg_data_dirs() -> list[Path]:
    """Return XDG data directories, defaulting to /usr/local/share:/usr/share."""
    raw = os.environ.get("XDG_DATA_DIRS", "")
    if not raw:
        return [Path("/usr/local/share"), Path("/usr/share")]
    return [Path(part) for part in raw.split(":") if part]


def application_dirs() -> list[Path]:
    """Return the ordered list of application directories to search."""
    dirs = [_xdg_data_home() / "applications"]
    for d in _xdg_data_dirs():
        dirs.append(d / "applications")
    return dirs


def _is_true(value: str) -> bool:
    """Return True if the config value is a truthy desktop flag."""
    return value.strip().lower() in ("true", "1")


def _read_section(path: Path) -> configparser.ConfigParser | None:
    """Read a .desktop file and return its ConfigParser, or None on error."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # type: ignore[assignment]
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None
    return parser


def _valid_entry(parser: configparser.ConfigParser) -> bool:
    """Check that the [Desktop Entry] section is a visible application."""
    if not parser.has_section("Desktop Entry"):
        return False
    section = parser["Desktop Entry"]
    return all(
        [
            bool(section.get("Name", "").strip()),
            bool(section.get("Exec", "").strip()),
            section.get("Type", "").strip() == "Application",
            not _is_true(section.get("NoDisplay", "")),
            not _is_true(section.get("Hidden", "")),
        ]
    )


def parse_desktop_file(path: Path, desktop_id: str) -> AppEntry | None:
    """Parse a single .desktop file into an AppEntry, or None if invalid."""
    parser = _read_section(path)
    if parser is None:
        return None
    if not _valid_entry(parser):
        return None
    section = parser["Desktop Entry"]
    name = section.get("Name", "").strip()
    generic_name = section.get("GenericName", "").strip()
    keywords_raw = section.get("Keywords", "")
    keywords = tuple(k.strip() for k in keywords_raw.split(";") if k.strip())
    exec_line = section.get("Exec", "").strip()
    startup_wm_class = section.get("StartupWMClass", "").strip()
    return AppEntry(
        desktop_id=desktop_id,
        name=name,
        generic_name=generic_name,
        keywords=keywords,
        exec_line=exec_line,
        startup_wm_class=startup_wm_class,
        path=path,
    )


def _desktop_id_for(base: Path, path: Path) -> str:
    """Compute the desktop_id for a .desktop file relative to its base dir."""
    rel = path.relative_to(base)
    return str(rel).replace("/", "-")


def load_index(dirs: Sequence[Path] | None = None) -> list[AppEntry]:
    """Walk application directories and build the index of AppEntry objects."""
    if dirs is None:
        dirs = application_dirs()
    seen: set[str] = set()
    entries: list[AppEntry] = []
    for base in dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.desktop")):
            if not path.is_file():
                continue
            desktop_id = _desktop_id_for(base, path)
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            entry = parse_desktop_file(path, desktop_id)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda e: e.desktop_id)


def _words(text: str) -> list[str]:
    """Split text on non-alphanumeric characters into word tokens."""
    return [w for w in re.split(r"[^\w]+", text) if w]


def _score(query: str, entry: AppEntry) -> int:
    """Score an entry against a normalised query (0 = no match)."""
    name = entry.name.casefold()
    generic = entry.generic_name.casefold()
    desktop_id = entry.desktop_id.casefold()
    id_no_ext = desktop_id.removesuffix(".desktop")
    keywords = tuple(k.casefold() for k in entry.keywords)

    if query in (name, generic, desktop_id, id_no_ext):
        return 3
    if any(query == kw for kw in keywords):
        return 3

    if name.startswith(query) or generic.startswith(query) or desktop_id.startswith(query):
        return 2

    tokens = query.split()
    if tokens:
        pool = [w.casefold() for w in _words(entry.name)]
        pool.extend(w.casefold() for w in _words(entry.generic_name))
        for kw in entry.keywords:
            pool.extend(w.casefold() for w in _words(kw))
        pool_set = set(pool)
        if all(tok in pool_set for tok in tokens):
            return 1

    return 0


def find_app(query: str, entries: Sequence[AppEntry] | None = None) -> AppEntry | Ambiguous | None:
    """Find the best-matching app for a spoken query."""
    if entries is None:
        entries = load_index()
    normalised = query.casefold().strip()
    if not normalised:
        return None

    scored: list[tuple[int, AppEntry]] = []
    for entry in entries:
        score = _score(normalised, entry)
        if score > 0:
            scored.append((score, entry))

    if not scored:
        return None

    best_score = max(s for s, _ in scored)
    best = [e for s, e in scored if s == best_score]

    if len(best) == 1:
        return best[0]

    candidates = tuple(sorted(best, key=lambda e: (e.name.casefold(), e.desktop_id)))
    return Ambiguous(candidates=candidates)
