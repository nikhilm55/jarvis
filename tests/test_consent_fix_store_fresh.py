"""M2 task 3, fix round 2: fresh store reads (F1), the lock off the loop (F2), F6, F7 and F10."""

import asyncio
import os
import re
import time
from collections.abc import Awaitable
from pathlib import Path

import pytest

from jarvis.config import ConsentSettings
from jarvis.consent.broker import AskAnswer, Broker
from jarvis.consent.scope import Scope
from jarvis.consent.session import SESSION_MAX_S, SessionGrants
from jarvis.consent.store import GrantStore, GrantsWriteError
from jarvis.policy.decision import TurnContext
from tests.consent_rig import MAIL_R, TEAMS_R, Rig, make_rig, says
from tests.store_files_rig import hold_lock, posix_only

TEAMS_READ = Scope.parse(TEAMS_R)


def on_disk(path: Path) -> dict[str, str]:
    return {str(g.scope): g.lifetime for g in GrantStore(path).all()}


def second_store(rig: Rig, tmp_path: Path) -> GrantStore:
    """Another store on the same file: a second Jarvis process, or the Permissions page."""
    return GrantStore(tmp_path / "grants.json")


# --- F1: a "never" or a revoke written elsewhere is honoured on the next check ----------------


def test_should_see_a_never_written_by_another_store_on_the_next_get(tmp_path: Path) -> None:
    path = tmp_path / "grants.json"
    first, other = GrantStore(path), GrantStore(path)
    assert first.get(TEAMS_READ) is None
    other.grant(TEAMS_READ, "never", "voice")
    seen = first.get(TEAMS_READ)
    assert seen is not None and seen.lifetime == "never"
    other.revoke(TEAMS_READ)
    assert first.all() == []  # a revoke is seen too
    other.grant(TEAMS_READ, "always", "voice")
    assert len(first.all()) == 1
    path.unlink()
    assert first.all() == []  # and so is a file that is gone


@pytest.mark.parametrize("first_touch", [False, True])
def test_should_deny_a_yolo_call_without_asking_when_another_store_wrote_a_never(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_touch: bool
) -> None:
    settings = ConsentSettings(yolo_asks_first_touch=first_touch)
    rig = make_rig(tmp_path, monkeypatch, says("always"), settings=settings)
    assert rig.require(TEAMS_R, mode="yolo") == "granted"  # YOLO lets it in
    asked = len(rig.asker.asked)
    second_store(rig, tmp_path).grant(TEAMS_READ, "never", "voice")
    for _ in range(3):
        assert rig.require(TEAMS_R, mode="yolo") == "denied"
    assert rig.checks()[-1]["reason"] == f"never: {TEAMS_R}"
    assert len(rig.asker.asked) == asked  # no question was put to the user


def test_should_ask_again_after_another_store_revokes_an_always(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always"))
    assert rig.require(TEAMS_R) == "granted"  # asked once, stored as always
    assert rig.require(TEAMS_R) == "granted"
    assert len(rig.asker.asked) == 1  # the grant holds without a question
    assert second_store(rig, tmp_path).revoke(TEAMS_READ)
    assert rig.require(TEAMS_R) == "granted"
    assert len(rig.asker.asked) == 2  # zero leaked calls: the very next check asked


class _InterruptedAsker:
    """The user is still answering when another store writes a never; then answers 'always'."""

    def __init__(self, other: GrantStore) -> None:
        self.other = other

    async def ask(
        self, scopes: tuple[Scope, ...], reason: str, ctx: TurnContext, offer_always: bool
    ) -> AskAnswer:
        self.other.grant(TEAMS_READ, "never", "key")
        return AskAnswer("always", "voice")


def test_should_not_let_a_stale_always_answer_replace_a_never(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch)
    broker = Broker(
        rig.store, rig.session, _InterruptedAsker(second_store(rig, tmp_path)), ConsentSettings()
    )
    ctx = TurnContext("t1", mode="balanced")
    assert asyncio.run(broker.require((TEAMS_R,), "to do that", ctx)) == "denied"
    assert on_disk(tmp_path / "grants.json") == {TEAMS_R: "never"}  # the never survived
    assert rig.store.get(TEAMS_READ) is not None
    assert rig.store.get(TEAMS_READ).lifetime == "never"  # type: ignore[union-attr]
    assert asyncio.run(broker.require((TEAMS_R,), "to do that", ctx)) == "denied"  # and still holds


def test_should_refuse_to_store_an_always_over_a_never_in_the_same_transaction(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grants.json"
    stale, other = GrantStore(path), GrantStore(path)
    other.grant(Scope.parse(MAIL_R), "never", "voice")
    with pytest.raises(GrantsWriteError, match="never"):
        stale.grant_all((TEAMS_READ, Scope.parse(MAIL_R)), "always", "voice")
    assert on_disk(path) == {MAIL_R: "never"}  # none of the scopes was stored


# --- F2: waiting for the lock does not freeze the event loop ----------------------------------


async def _watch_loop(work: Awaitable[object]) -> float:
    """The longest gap between two ticks of a 10 ms ticker while `work` runs."""
    gaps: list[float] = []

    async def ticker() -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    try:
        await work
    finally:
        task.cancel()
    return max(gaps, default=9.9)


@posix_only
@pytest.mark.parametrize("case", ["touch", "commit"])
def test_should_keep_the_event_loop_ticking_while_require_waits_for_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    path = tmp_path / "grants.json"
    if case == "touch":
        GrantStore(path).grant(TEAMS_READ, "always", "voice")  # granted: only `touch` locks
    store = GrantStore(path, lock_deadline_s=0.4)
    broker = Broker(store, SessionGrants(), _Script(says("always")), ConsentSettings())
    ctx = TurnContext("t1", mode="balanced")
    monkeypatch.setattr("jarvis.consent.broker.audit", lambda *a, **k: None)
    monkeypatch.setattr("jarvis.consent.store.audit", lambda *a, **k: None)

    async def scenario() -> tuple[float, str]:
        call = asyncio.ensure_future(broker.require((TEAMS_R,), "to do that", ctx))
        gap = await _watch_loop(call)
        return gap, call.result()

    started = time.monotonic()
    with hold_lock(path):
        gap, verdict = asyncio.run(scenario())
    assert time.monotonic() - started >= 0.35  # it really waited for the lock
    assert gap < 0.1  # and the loop kept running meanwhile
    assert verdict == ("granted" if case == "touch" else "denied")


class _Script:
    def __init__(self, answer: AskAnswer) -> None:
        self.answer = answer

    async def ask(
        self, scopes: tuple[Scope, ...], reason: str, ctx: TurnContext, offer_always: bool
    ) -> AskAnswer:
        return self.answer


# --- F6: a clock set back is not a longer session ---------------------------------------------


def test_should_expire_a_session_grant_when_the_clock_goes_backwards() -> None:
    now = [1000.0]
    grants = SessionGrants(lambda: now[0])
    grants.grant(TEAMS_READ, "session", "t1")
    now[0] -= 365 * 24 * 3600  # the wall clock was set back a year (the non-Linux fallback clock)
    assert not grants.holds(TEAMS_READ, "t1")
    now[0] = 1000.0
    grants.grant(TEAMS_READ, "session", "t1")
    now[0] += SESSION_MAX_S - 1
    assert grants.holds(TEAMS_READ, "t1")  # the normal limit is unchanged


# --- F7: the audit says what happened to an answer ---------------------------------------------


def test_should_audit_that_an_answer_was_not_stored_when_the_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always"))

    def broken(src: object, dst: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr("jarvis.consent.store.os.replace", broken)
    assert rig.require(TEAMS_R) == "denied"
    messages = [m for m, _ in rig.audit]
    assert messages.index("consent answer") < messages.index("consent answer not stored")
    record = dict(rig.audit)["consent answer not stored"]
    assert record["decision"] == "denied" and "GrantsWriteError" in str(record["reason"])
    assert rig.checks()[-1]["decision"] == "denied"
    assert rig.store.all() == [] and not (tmp_path / "grants.json").exists()


def test_should_audit_before_it_stores_so_no_grant_exists_without_a_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("always"))
    on_disk_at_audit: list[bool] = []

    def record(source: str, message: str, **fields: object) -> None:
        if message == "grant change":
            on_disk_at_audit.append((tmp_path / "grants.json").exists())

    monkeypatch.setattr("jarvis.consent.store.audit", record)
    assert rig.require(TEAMS_R) == "granted"
    assert on_disk_at_audit == [False]  # the record came first (#192's rule still holds)
    assert (tmp_path / "grants.json").exists()


# --- F10: one NO_TURN sentinel ------------------------------------------------------------------


@pytest.mark.parametrize("module", ["mcp/server.py", "orchestrator/trace.py"])
def test_should_import_the_no_turn_sentinel_instead_of_repeating_it(module: str) -> None:
    source = (Path(__file__).parents[1] / "src" / "jarvis" / module).read_text(encoding="utf-8")
    assert '"no-turn"' not in source
    assert re.search(r"from jarvis\.consent\.session import .*\bNO_TURN\b", source)
    assert os.path.exists(Path(__file__).parents[1] / "src" / "jarvis" / module)
