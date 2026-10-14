"""Tests for jarvis.desktop.client against the fake worker."""

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from jarvis.desktop.client import DesktopClient, DesktopError

FAKE = Path(__file__).parent / "fixtures" / "fake_desktop_worker.py"


def _client(tmp_path: Path, mode: str, **kw: Any) -> DesktopClient:
    return DesktopClient([sys.executable, str(FAKE), mode, str(tmp_path)], **kw)


def _starts(tmp_path: Path) -> int:
    p = tmp_path / "starts.txt"
    if not p.exists():
        return 0
    return len(p.read_text(encoding="utf-8").splitlines())


def _requests(tmp_path: Path) -> list[str]:
    p = tmp_path / "requests.txt"
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8").splitlines()


CASES = [
    ("open_app", ("x",), "open_app", {"query": "x"}),
    ("close_app", ("x",), "close_app", {"query": "x"}),
    ("volume_get", (), "volume_get", {}),
    ("volume_set", (30,), "volume_set", {"pct": 30}),
    ("volume_step", (5,), "volume_step", {"delta": 5}),
    ("mute", (True,), "mute", {"on": True}),
]


@pytest.mark.parametrize(("name", "args", "op", "exp"), CASES)
def test_should_echo_op_and_args_when_ok(
    tmp_path: Path, name: str, args: tuple[object, ...], op: str, exp: dict[str, object]
) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "ok")
        try:
            r = await getattr(c, name)(*args)
            assert r["op"] == op
            assert r["args"] == exp
        finally:
            await c.close()

    asyncio.run(scenario())


def test_should_reuse_worker_pid_when_two_calls(tmp_path: Path) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "ok")
        try:
            r1 = await c.volume_get()
            r2 = await c.volume_get()
            assert r1["pid"] == r2["pid"]
            assert _starts(tmp_path) == 1
        finally:
            await c.close()

    asyncio.run(scenario())


def test_should_not_clash_ids_when_five_concurrent(tmp_path: Path) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "ok")
        try:
            results = await asyncio.gather(*[c.volume_get() for _ in range(5)])
            assert len(results) == 5
            assert _starts(tmp_path) == 1
        finally:
            await c.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("name", "args", "op"),
    [
        ("close_app", ("x",), "close_app"),
        ("volume_get", (), "volume_get"),
        ("volume_set", (30,), "volume_set"),
        ("mute", (True,), "mute"),
    ],
)
def test_should_retry_idempotent_when_crash_once(
    tmp_path: Path, name: str, args: tuple[object, ...], op: str
) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "crash_once")
        try:
            r = await getattr(c, name)(*args)
            assert r["op"] == op
            assert _starts(tmp_path) == 2
            assert _requests(tmp_path) == [op, op]
        finally:
            await c.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("name", "args", "op"),
    [
        ("open_app", ("x",), "open_app"),
        ("volume_step", (5,), "volume_step"),
    ],
)
def test_should_not_retry_non_idempotent_when_crash_once(
    tmp_path: Path, name: str, args: tuple[object, ...], op: str
) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "crash_once")
        try:
            with pytest.raises(DesktopError) as exc:
                await getattr(c, name)(*args)
            assert exc.value.code == "INTERNAL"
            assert "cannot be safely repeated" in exc.value.message
            assert _starts(tmp_path) == 1
            assert _requests(tmp_path) == [op]
            r = await c.volume_get()
            assert r["op"] == "volume_get"
            assert _starts(tmp_path) == 2
        finally:
            await c.close()

    asyncio.run(scenario())


def test_should_raise_crashed_when_crash_always(tmp_path: Path) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "crash_always")
        try:
            with pytest.raises(DesktopError) as exc:
                await c.volume_get()
            assert exc.value.code == "INTERNAL"
            assert exc.value.message == "desktop worker crashed"
            assert _starts(tmp_path) == 2
        finally:
            await c.close()

    asyncio.run(scenario())


def test_should_raise_worker_error_when_error_mode(tmp_path: Path) -> None:
    async def scenario() -> None:
        c = _client(tmp_path, "error")
        try:
            with pytest.raises(DesktopError) as exc:
                await c.volume_get()
            assert exc.value.code == "NOT_FOUND"
            assert exc.value.message == "nope"
            assert len(_requests(tmp_path)) == 1
        finally:
            await c.close()

    asyncio.run(scenario())
