"""The persistent consent grants: "always" and "never", in `data_dir()/grants.json` (R87).

The file is private (0600), schema-versioned and replaced atomically. A file that is damaged,
hostile or from the future is never read as data and never overwritten: it is set aside under
`grants.json.bad-<timestamp>` and the store starts with no grants, so everything asks again. If it
cannot even be set aside (a read-only directory) the store still starts, empty, and refuses writes.

R100: every change takes an exclusive lock, re-reads the file and applies only its own delta to what
it finds, so two stores (or processes) on one file never lose each other's grants, "never" included.
On POSIX the lock is `fcntl.flock` on `grants.json.lock` (0600, same directory). Elsewhere it is a
process-wide lock: it covers every store in this process, not other processes.
"""

import contextlib
import json
import os
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from jarvis.consent.scope import Scope
from jarvis.log import audit, get_logger

if sys.platform != "win32":
    import fcntl

Lifetime = Literal["once", "session", "always", "never"]
GrantMethod = Literal["voice", "typed", "button", "key", "settings"]

SCHEMA_VERSION = 1
_STORED = ("always", "never")
_METHODS = ("voice", "typed", "button", "key", "settings")
_GRANT_KEYS = {"scope", "lifetime", "method", "granted_at", "last_used"}

logger = get_logger("consent")

_PROCESS_LOCK = threading.RLock()  # the lock where there is no flock


class GrantsFileError(RuntimeError):
    """The grants file is unusable and could not even be set aside."""


class GrantsWriteError(RuntimeError):
    """A write failed or did not verify; the grants are unchanged."""


@dataclass(frozen=True)
class Grant:
    """One stored grant of a scope."""

    scope: Scope
    lifetime: Lifetime
    method: GrantMethod
    granted_at: datetime
    last_used: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unstamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("a timestamp must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("a timestamp must carry a time zone")
    return parsed.astimezone(UTC)


def _document(grants: dict[Scope, Grant]) -> dict[str, object]:
    return {
        "version": SCHEMA_VERSION,
        "grants": [
            {
                "scope": str(g.scope),
                "lifetime": g.lifetime,
                "method": g.method,
                "granted_at": _stamp(g.granted_at),
                "last_used": _stamp(g.last_used),
            }
            for g in sorted(grants.values(), key=lambda g: g.scope)
        ],
    }


def _entry(raw: object) -> Grant:
    if not isinstance(raw, dict) or set(raw) != _GRANT_KEYS:
        raise ValueError("a grant must be an object with exactly the known fields")
    scope, lifetime, method = raw["scope"], raw["lifetime"], raw["method"]
    if not isinstance(scope, str) or lifetime not in _STORED or method not in _METHODS:
        raise ValueError("a grant has a field of the wrong type or an unknown value")
    last_used = raw["last_used"]
    return Grant(
        Scope.parse(scope),
        cast(Lifetime, lifetime),
        cast(GrantMethod, method),
        _unstamp(raw["granted_at"]),
        None if last_used is None else _unstamp(last_used),
    )


def _parse(data: object) -> dict[Scope, Grant]:
    """The grants in a decoded document; anything not exactly the schema is a ValueError."""
    if not isinstance(data, dict) or set(data) != {"version", "grants"}:
        raise ValueError("the file must be an object with `version` and `grants`")
    version = data["version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version {version!r}")
    if not isinstance(data["grants"], list):
        raise ValueError("`grants` must be a list")
    grants: dict[Scope, Grant] = {}
    for raw in data["grants"]:
        grant = _entry(raw)
        if grant.scope in grants:
            raise ValueError(f"{grant.scope} appears twice")
        grants[grant.scope] = grant
    return grants


class GrantStore:
    """The always/never grants. Every change is audited first, then written and verified."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = _now) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._grants: dict[Scope, Grant] = {}
        self._problem: str | None = None
        self._stuck = False  # an unusable file that could not be set aside: nothing may be written
        self._load()

    @property
    def problem(self) -> str | None:
        """None, or what was wrong with the file that was set aside at start-up."""
        return self._problem

    def get(self, scope: Scope) -> Grant | None:
        return self._grants.get(scope)

    def all(self) -> list[Grant]:
        return sorted(self._grants.values(), key=lambda g: g.scope)

    def grant(self, scope: Scope, lifetime: Lifetime, method: GrantMethod) -> Grant:
        """Store `always` or `never` for `scope`, replacing any earlier grant of it."""
        return self.grant_all((scope,), lifetime, method)[0]

    def grant_all(
        self, scopes: Sequence[Scope], lifetime: Lifetime, method: GrantMethod
    ) -> list[Grant]:
        """Store `always` or `never` for every scope in ONE transaction: all of them or none."""
        if lifetime not in _STORED:
            raise ValueError(f"only 'always' and 'never' are stored, not {lifetime!r}")
        if method not in _METHODS:
            raise ValueError(f"unknown grant method {method!r}")
        made = [Grant(scope, lifetime, method, self._clock()) for scope in scopes]

        def plan(held: dict[Scope, Grant]) -> tuple[list[dict[str, str]], int, dict[Scope, Grant]]:
            records = [
                {"op": "grant", "scope": str(g.scope), "lifetime": lifetime, "method": method}
                for g in made
            ]
            return records, 1, held | {g.scope: g for g in made}

        self._change(plan)
        return made

    def revoke(self, scope: Scope) -> bool:
        """Remove the grant of `scope`; True when there was one."""
        found = False

        def plan(held: dict[Scope, Grant]) -> tuple[list[dict[str, str]], int, dict[Scope, Grant]]:
            nonlocal found
            old = held.get(scope)
            found = old is not None
            record = {"op": "revoke", "scope": str(scope)}
            if old is not None:
                record |= {"lifetime": old.lifetime, "method": old.method}
            return [record], int(found), {s: g for s, g in held.items() if s != scope}

        self._change(plan)
        return found

    def revoke_all(self) -> int:
        """Remove every "always" grant (a "never" stays); returns how many."""
        removed = 0

        def plan(held: dict[Scope, Grant]) -> tuple[list[dict[str, str]], int, dict[Scope, Grant]]:
            nonlocal removed
            rest = {s: g for s, g in held.items() if g.lifetime != "always"}
            removed = len(held) - len(rest)
            return [{"op": "revoke_all", "scope": "*"}], removed, rest

        self._change(plan)
        return removed

    def reset_all_to_ask(self) -> int:
        """Remove every grant, "never" included, so every scope asks again; returns how many."""
        removed = 0

        def plan(held: dict[Scope, Grant]) -> tuple[list[dict[str, str]], int, dict[Scope, Grant]]:
            nonlocal removed
            removed = len(held)
            return [{"op": "reset_all_to_ask", "scope": "*"}], removed, {}

        self._change(plan)
        return removed

    def touch(self, scope: Scope) -> None:
        """Record that `scope` was just used; an unknown scope is ignored."""
        with self._exclusive():
            self._refresh()
            held = self._grants.get(scope)
            if held is not None:
                self._commit({**self._grants, scope: replace(held, last_used=self._clock())})

    def _change(
        self,
        plan: Callable[[dict[Scope, Grant]], tuple[list[dict[str, str]], int, dict[Scope, Grant]]],
    ) -> None:
        """Under the lock: re-read, audit every record first (a failure changes nothing), write."""
        with self._exclusive():
            self._refresh()
            records, count, grants = plan(self._grants)
            for record in records:
                audit("consent", "grant change", count=count, **record)
            if grants != self._grants:
                self._commit(grants)

    def _commit(self, grants: dict[Scope, Grant]) -> None:
        """Write `grants`; they replace the ones in memory only once the file is verified."""
        self._write(_document(grants))
        self._grants = grants

    @contextlib.contextmanager
    def _exclusive(self) -> Iterator[None]:
        """One writer at a time across stores and processes (R100); the lock file is 0600."""
        with self._lock:
            if self._stuck:
                raise GrantsWriteError(
                    "the unusable grants file could not be set aside (see problem)"
                )
            if sys.platform == "win32":
                with _PROCESS_LOCK:
                    yield
                return
            fd = self._acquire()
            try:
                yield
            finally:
                os.close(fd)  # closing the descriptor releases the lock

    def _acquire(self) -> int:
        """Open the 0600 lock file and take the exclusive flock; the descriptor holds it."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(f"{self._path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as error:
            raise GrantsWriteError(f"cannot lock the consent grants: {error}") from error
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as error:
            os.close(fd)
            raise GrantsWriteError(f"cannot lock the consent grants: {error}") from error
        return fd

    def _refresh(self) -> None:
        """Re-read the file (under the lock): what is on disk now is the state to change."""
        self._load()
        if self._stuck:
            raise GrantsWriteError("the unusable grants file could not be set aside (see problem)")

    def _load(self) -> None:
        path = self._path
        if not path.is_symlink() and not path.exists():
            self._grants = {}  # no file: no grants
            return
        try:
            if path.is_symlink():
                raise ValueError("the grants file is a symbolic link")
            self._grants = _parse(json.loads(path.read_bytes().decode("utf-8")))
        except (OSError, ValueError) as error:  # JSON and UTF-8 errors are ValueErrors
            self._grants = {}
            self._set_aside(str(error) or type(error).__name__)

    def _set_aside(self, why: str) -> None:
        """Keep the unusable file as `.bad-<timestamp>` (a link is renamed, never followed)."""
        stamp = self._clock().astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        moved = self._path.with_name(f"{self._path.name}.bad-{stamp}")
        try:
            os.replace(self._path, moved)
        except OSError as error:  # the file stays where it is, and nothing may overwrite it
            self._stuck = True
            self._problem = (
                f"the grants file was unusable ({why}) and could not be set aside: {error}"
            )
            logger.warning(self._problem, extra={"path": str(self._path)})
            return
        self._problem = f"the grants file was unusable ({why}) and is kept as {moved.name}"
        logger.warning(self._problem, extra={"path": str(moved)})
        try:
            audit("consent", "grants file unusable", why=why, kept_as=moved.name)
        except Exception:
            logger.exception("audit unavailable")

    def _write(self, document: dict[str, object]) -> None:
        """Atomically replace the file with `document`, then check what is on disk."""
        text = json.dumps(document, indent=2, sort_keys=True) + "\n"
        tmp: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".grants-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:  # mkstemp makes it 0600
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            self._verify(Path(tmp), document)  # a bad copy never replaces the good file
            os.replace(tmp, self._path)
            tmp = None
            self._sync_directory()
            self._verify(self._path, document)
        except (OSError, ValueError) as error:
            raise GrantsWriteError(f"cannot save the consent grants: {error}") from error
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)

    def _verify(self, path: Path, intended: dict[str, object]) -> None:
        if json.loads(path.read_bytes().decode("utf-8")) != intended:
            raise ValueError("what was written is not what was meant to be written")

    def _sync_directory(self) -> None:
        if sys.platform == "win32":
            return
        fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
