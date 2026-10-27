"""The kill switch (FR-SAFE-04): voice, Ctrl+Alt+Esc and HUD Stop all stop everything."""

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis import paths
from jarvis.hotkey import Hotkey
from jarvis.hud.server import HudServer
from jarvis.killswitch import KillSwitch
from tests.core_rig import CoreRig
from tests.listener_rig import seg
from tests.orchestrator_rig import until


def audits() -> list[dict[str, Any]]:
    log = paths.data_dir() / "logs" / "audit.jsonl"
    if not log.exists():
        return []
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r.get("name") == "jarvis.killswitch"]


# --- KillSwitch ----------------------------------------------------------------------------------


def test_should_kill_the_registered_groups_stop_the_turn_and_audit_the_source() -> None:
    killed: list[int] = []
    stopped: list[str] = []

    async def stop() -> None:
        stopped.append("stop")

    switch = KillSwitch(stop, kill_group=killed.append)
    switch.register_process(41)
    done = switch.register_process(42)
    switch.register_process(43)
    done()  # 42 ended on its own
    asyncio.run(switch.trigger("hud"))
    assert killed == [41, 43] and stopped == ["stop"]
    [record] = audits()
    assert (record["trigger"], record["groups"]) == ("hud", 2)
    asyncio.run(switch.trigger("voice"))
    assert killed == [41, 43]  # a group is killed once, then forgotten


def test_should_still_stop_the_turn_when_a_kill_fails_and_never_raise() -> None:
    stopped: list[str] = []

    def kill(pgid: int) -> None:
        raise PermissionError(pgid)

    async def stop() -> None:
        stopped.append("stop")
        raise RuntimeError("half-way")

    switch = KillSwitch(stop, kill_group=kill)
    switch.register_process(7)
    asyncio.run(switch.trigger("hotkey"))  # no raise
    assert stopped == ["stop"]
    assert audits()[-1]["trigger"] == "hotkey"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX process groups")
def test_should_kill_a_real_process_group_with_its_children() -> None:
    script = "import subprocess, time; subprocess.Popen(['sleep', '60']); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", script], start_new_session=True)
    try:

        async def stop() -> None:
            return None

        switch = KillSwitch(stop)
        switch.register_process(os.getpgid(proc.pid))
        started = time.monotonic()
        asyncio.run(switch.trigger("voice"))
        assert proc.wait(timeout=5) == -9
        assert time.monotonic() - started < 0.3  # FR-SAFE-04: within 300 ms
        group = subprocess.run(["pgrep", "-g", str(proc.pid)], capture_output=True, check=False)
        assert group.stdout == b""  # the child went with it
    finally:
        if proc.poll() is None:
            proc.kill()


# --- the orchestrator: voice, hotkey and re-warming --------------------------------------------


class FakeHotkey:
    def __init__(self, on_press: Callable[[], None], *, grabbed: bool = True) -> None:
        self.on_press = on_press
        self.grabbed = grabbed
        self.stopped = False

    def start(self) -> bool:
        return self.grabbed

    def stop(self) -> None:
        self.stopped = True


def _held_turn(tmp_path: Path, stop_with: str) -> tuple[CoreRig, list[FakeHotkey]]:
    hotkeys: list[FakeHotkey] = []

    def factory(on_press: Callable[[], None]) -> FakeHotkey:
        hotkeys.append(FakeHotkey(on_press))
        return hotkeys[-1]

    async def scenario() -> CoreRig:
        rig = CoreRig(tmp_path, ["Jarvis, do a long thing", "Jarvis, stop"])
        rig.orchestrator._hotkey_factory = factory
        assert rig.brain is not None
        rig.brain.release = asyncio.Event()  # the turn only ends by cancellation
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await asyncio.wait_for(rig.brain.entered.wait(), 5)
            if stop_with == "voice":
                rig.feed.push(seg())
            else:  # the hotkey thread calls on_press
                await asyncio.to_thread(hotkeys[0].on_press)
            await until(lambda: len(rig.records()) == 1)
            await until(lambda: rig.events.count("brain.start") == 2)
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()
        return rig

    return asyncio.run(scenario()), hotkeys


@pytest.mark.parametrize("stop_with", ["voice", "hotkey"])
def test_should_cancel_the_turn_audit_it_and_rewarm_the_brain(
    tmp_path: Path, stop_with: str
) -> None:
    rig, hotkeys = _held_turn(tmp_path, stop_with)
    [record] = rig.records()
    assert record["drop_reason"] == "cancelled"
    assert [a["trigger"] for a in audits()] == [stop_with]
    assert rig.events.count("brain.start") == 2  # warmed at start, and again after the stop
    assert hotkeys[0].stopped  # the grab is released on the way out


def test_should_run_without_the_hotkey_when_it_cannot_be_grabbed(tmp_path: Path) -> None:
    async def scenario() -> CoreRig:
        rig = CoreRig(tmp_path, [])
        rig.orchestrator._hotkey_factory = lambda on_press: FakeHotkey(on_press, grabbed=False)
        run = asyncio.create_task(rig.orchestrator.run())
        rig.feed.end()
        await asyncio.wait_for(run, 10)
        return rig

    assert "brain.close" in asyncio.run(scenario()).events


# --- HUD Stop ------------------------------------------------------------------------------------


def _post_stop(on_stop: Any, *, token: bool = True) -> int:
    async def scenario() -> int:
        server = HudServer(on_stop=on_stop)
        await server.start()
        try:
            url = server.url.removesuffix("/hud") + "/stop"
            headers = {"Authorization": f"Bearer {server.token}"} if token else {}
            async with httpx.AsyncClient() as client:
                return (await client.post(url, headers=headers)).status_code
        finally:
            await server.close()

    return asyncio.run(scenario())


def test_should_trigger_the_kill_switch_from_the_hud_stop_button() -> None:
    pressed: list[str] = []

    async def on_stop() -> None:
        pressed.append("stop")

    assert _post_stop(on_stop) == 204 and pressed == ["stop"]
    assert _post_stop(on_stop, token=False) == 401 and pressed == ["stop"]
    assert _post_stop(None) == 409


# --- the hotkey grab (python-xlib, faked) ---------------------------------------------------------


class FakeRoot:
    def __init__(self) -> None:
        self.grabs: list[int] = []

    def grab_key(self, keycode: int, modifiers: int, *args: Any, onerror: Any = None) -> None:
        self.grabs.append(modifiers)
        self.onerror = onerror


class FakeEvent:
    def __init__(self, kind: int, detail: int) -> None:
        self.type = kind
        self.detail = detail


class FakeDisplay:
    def __init__(self, events: list[FakeEvent], *, taken: bool = False) -> None:
        self.root = FakeRoot()
        self.events = events
        self.taken = taken
        self.closed = False
        self.pipe = -1  # a readable fd the listener can select on

    def screen(self) -> Any:
        return type("Screen", (), {"root": self.root})()

    def keysym_to_keycode(self, keysym: int) -> int:
        return 9

    def sync(self) -> None:
        if self.taken:  # the X server refused the grab: another client owns it
            from Xlib import error  # noqa: PLC0415

            self.root.onerror(object.__new__(error.BadAccess), None)

    def pending_events(self) -> int:
        return len(self.events)

    def next_event(self) -> FakeEvent:
        return self.events.pop(0)

    def fileno(self) -> int:
        return self.pipe

    def close(self) -> None:
        self.closed = True


def test_should_grab_ctrl_alt_esc_with_every_lock_and_call_back_on_press() -> None:
    from Xlib import X  # noqa: PLC0415

    presses: list[str] = []
    events = [FakeEvent(X.KeyPress, 10), FakeEvent(X.KeyPress, 9), FakeEvent(X.KeyRelease, 9)]
    display = FakeDisplay(events)
    read, write = os.pipe()
    display.pipe = read
    hotkey = Hotkey(lambda: presses.append("press"), display=display)
    try:
        assert hotkey.start() is True
        base = X.ControlMask | X.Mod1Mask
        assert display.root.grabs == [
            base,
            base | X.LockMask,
            base | X.Mod2Mask,
            base | X.LockMask | X.Mod2Mask,
        ]
        deadline = time.monotonic() + 2
        while not presses and time.monotonic() < deadline:
            time.sleep(0.01)
        assert presses == ["press"]  # only the grabbed key's press
    finally:
        hotkey.stop()
        os.close(read)
        os.close(write)
    assert display.closed


def test_should_report_a_hotkey_owned_by_another_app() -> None:
    assert Hotkey(lambda: None, display=FakeDisplay([], taken=True)).start() is False


def test_should_be_off_without_an_x_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    assert Hotkey(lambda: None).start() is False
