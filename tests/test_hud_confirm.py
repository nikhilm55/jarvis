"""The HUD confirmation card (FR-SAFE-07, R82): POST /answer, the card logic, card-only input."""

import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from jarvis.config import HudSettings
from jarvis.confirm import HudAnswer, HudAnswers
from jarvis.hud import runtime
from jarvis.hud.page import read_page
from jarvis.hud.server import HudServer
from jarvis.orchestrator.hud import HudEvent
from tests.hud_rig import next_event, stream, until
from tests.test_hud_clickthrough import FakeX11, FakeXext, _load_window
from tests.test_hud_window import WINDOW_PATH

# --- POST /answer --------------------------------------------------------------------------------


def _post(
    answers: HudAnswers | None, body: object, *, token: bool = True, open_question: bool = True
) -> tuple[int, HudAnswer | None]:
    async def scenario() -> tuple[int, HudAnswer | None]:
        server = HudServer(answers=answers)
        await server.start()
        try:
            question = answers.open() if answers is not None and open_question else None
            url = server.url.removesuffix("/hud") + "/answer"
            headers = {"Authorization": f"Bearer {server.token}"} if token else {}
            content = body if isinstance(body, bytes) else json.dumps(body).encode()
            async with httpx.AsyncClient() as client:
                response = await client.post(url, content=content, headers=headers)
            got = question.result() if question is not None and question.done() else None
            return response.status_code, got
        finally:
            await server.close()

    return asyncio.run(scenario())


@pytest.mark.parametrize("method", ["button", "key", "typed"])
def test_should_hand_the_answer_to_the_open_question(method: str) -> None:
    status, got = _post(HudAnswers(), {"answer": " yes ", "method": method})
    assert (status, got) == (204, HudAnswer("yes", method))  # type: ignore[arg-type]


def test_should_say_409_when_no_question_is_open() -> None:
    assert _post(HudAnswers(), {"answer": "yes", "method": "button"}, open_question=False)[0] == 409
    assert _post(None, {"answer": "yes", "method": "button"})[0] == 409


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        ["yes"],
        {"answer": "yes"},
        {"answer": "yes", "method": "voice"},  # voice answers come from the microphone only
        {"answer": "", "method": "typed"},
        {"answer": "   ", "method": "typed"},
        {"answer": "x" * 201, "method": "typed"},
        {"answer": 1, "method": "key"},
    ],
)
def test_should_refuse_a_malformed_answer_and_leave_the_question_open(body: object) -> None:
    status, got = _post(HudAnswers(), body)
    assert (status, got) == (400, None)


def test_should_refuse_an_answer_without_the_token() -> None:
    status, got = _post(HudAnswers(), {"answer": "yes", "method": "button"}, token=False)
    assert status == 401 and got is None


def test_should_wire_the_answers_into_the_hud_server(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []

    class Spy(HudServer):
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)
            super().__init__(**kwargs)

    class NoWindow:
        returncode = None

        async def wait(self) -> int:
            await asyncio.sleep(3600)
            return 0

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    def spawner(python: str, url: str, token: str) -> Any:
        async def spawn() -> NoWindow:
            return NoWindow()

        return spawn

    answers = HudAnswers()
    monkeypatch.setattr(runtime, "HudServer", Spy)

    async def scenario() -> None:
        async with runtime.running_hud(HudSettings(), spawner=spawner, answers=answers):
            pass

    asyncio.run(scenario())
    assert built == [{"answers": answers, "on_stop": None}]


# --- the card logic, run under node --------------------------------------------------------------


def _card_logic(expression: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed, so the page's card logic cannot run")
    page = read_page()
    start = page.index("/* CARD LOGIC")
    end = page.index("/* END CARD LOGIC */")
    script = page[start:end] + f"\nprocess.stdout.write(JSON.stringify({expression}));\n"
    done = subprocess.run(
        [node, "-e", script], capture_output=True, encoding="utf-8", timeout=30, check=True
    )
    return json.loads(done.stdout)


def test_should_show_confirm_and_both_keys_for_a_voice_question() -> None:
    model = _card_logic("cardModel({kind: 'voice'})")
    assert model["yes"] is True and model["keys"] == ["Y", "N"] and model["phrase"] == ""


def test_should_show_confirm_but_no_yes_key_for_a_click_question() -> None:
    model = _card_logic("cardModel({kind: 'click'})")
    assert model["yes"] is True and model["keys"] == ["N"]


def test_should_show_the_phrase_and_no_confirm_button_for_the_guardrail() -> None:
    model = _card_logic("cardModel({kind: 'guardrail', phrase: 'confirm rm ~/a'})")
    assert model["yes"] is False
    assert model["phrase"] == "confirm rm ~/a"
    assert "confirm rm ~/a" in model["say"] and "confirm rm ~/a" in model["placeholder"]


@pytest.mark.parametrize(
    ("key", "kind", "expected"),
    [
        ("y", "voice", "yes"),
        ("Y", "voice", "yes"),
        ("y", "click", None),
        ("y", "guardrail", None),
        ("n", "click", "no"),
        ("N", "guardrail", "no"),
        ("Escape", "voice", "no"),
        ("Enter", "voice", None),
        ("x", "voice", None),
    ],
)
def test_should_map_keys_to_answers_by_kind(key: str, kind: str, expected: str | None) -> None:
    assert _card_logic(f"keyAnswer({json.dumps(key)}, {json.dumps(kind)})") == expected


def test_should_post_answers_with_the_token_and_take_the_card_down_on_close() -> None:
    page = read_page()
    assert "fetch('/answer'" in page and "'Bearer ' + token" in page
    assert "if ((ev.extra || {}).closed) { closeCard(); return; }" in page
    assert "windowMode(false)" in page[page.index("function closeCard()") :]


# --- the window takes input over the card only (R82) ---------------------------------------------


def test_should_take_input_over_the_card_rectangle_in_window_pixels() -> None:
    window = _load_window()
    raw = json.dumps({"interactive": True, "rect": [10.5, 20, 300, 200], "scale": 2})
    assert window.parse_mode(raw) == (21, 40, 600, 400)  # inside the 2x window (1224 x 840)
    raw = json.dumps({"interactive": True, "rect": [500, 300, 300, 300], "scale": 2})
    assert window.parse_mode(raw) == (1000, 600, 2 * window.WINDOW_WIDTH - 1000, 240)


def test_should_clip_the_rectangle_to_the_window() -> None:
    window = _load_window()
    raw = json.dumps({"interactive": True, "rect": [-5, 300, 9000, 9000]})
    assert window.parse_mode(raw) == (0, 300, window.WINDOW_WIDTH, window.WINDOW_HEIGHT - 300)


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"interactive": False, "rect": [0, 0, 10, 10]}),
        json.dumps({"interactive": "yes", "rect": [0, 0, 10, 10]}),
        json.dumps({"interactive": True}),
        json.dumps({"interactive": True, "rect": [0, 0, 0, 10]}),
        json.dumps({"interactive": True, "rect": [0, 0, 10, 10], "scale": 0}),
        json.dumps({"interactive": True, "rect": ["a", 0, 10, 10]}),
        json.dumps({"interactive": True, "rect": [9000, 9000, 10, 10]}),
        "not json",
        "[]",
    ],
)
def test_should_stay_click_through_for_anything_but_a_valid_card(raw: str) -> None:
    assert _load_window().parse_mode(raw) is None


def test_should_set_one_input_rectangle_or_none() -> None:
    window = _load_window()
    x11, xext = FakeX11(), FakeXext()
    assert window.set_input_shape(4242, (1, 2, 3, 4), x11=x11, xext=xext) is True
    _, xid, kind, _, _, rects, count, op, _ = xext.calls[0]
    assert (xid, kind, count, op) == (4242, 2, 1, 0)
    assert (rects[0].x, rects[0].y, rects[0].width, rects[0].height) == (1, 2, 3, 4)
    window.set_input_shape(4242, None, x11=x11, xext=xext)
    assert xext.calls[1] == (77, 4242, 2, 0, 0, None, 0, 0, 0)


# --- live: the real window over the real X server (R82) ------------------------------------------


@pytest.mark.desktop
@pytest.mark.skipif(
    not os.environ.get("DISPLAY") or os.environ.get("JARVIS_LIVE_DESKTOP") != "1",
    reason="live desktop test: set DISPLAY and JARVIS_LIVE_DESKTOP=1",
)
def test_should_take_input_over_the_card_only_while_it_shows() -> None:
    window = _load_window()

    async def scenario() -> tuple[list[Any], list[Any], list[Any]]:
        server = HudServer(answers=HudAnswers())
        await server.start()
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/python3",
            "-I",
            str(WINDOW_PATH),
            "--url",
            server.url,
            env={**os.environ, window.TOKEN_ENV: server.token},
        )
        try:
            await until(lambda: server.client_count == 1)
            before = await asyncio.to_thread(_input_rectangles)
            extra: dict[str, object] = {"kind": "voice", "phrase": None}
            await server.publish(HudEvent("confirm", "Close window Firefox?", extra))
            during = await _settled(lambda r: len(r) == 1)
            await server.publish(HudEvent("confirm", "", {"closed": True}))
            after = await _settled(lambda r: r == [])
            process.terminate()
            assert await asyncio.wait_for(process.wait(), 5) == 0
            return before, during, after
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await server.close()

    before, during, after = asyncio.run(scenario())
    assert before == [] and after == []
    card = during[0]
    assert 200 < card.width <= window.WINDOW_WIDTH * 2 and 100 < card.height < 400


async def _settled(done: Callable[[list[Any]], bool]) -> list[Any]:
    rects: list[Any] = []
    for _ in range(100):
        rects = await asyncio.to_thread(_input_rectangles)
        if done(rects):
            return rects
        await asyncio.sleep(0.05)
    return rects


def _input_rectangles() -> list[Any]:
    from Xlib import display  # noqa: PLC0415 - only the live test needs an X connection
    from Xlib.ext import shape  # noqa: PLC0415

    def find(node: Any) -> Any:
        if (node.get_wm_name() or "") == "Jarvis HUD":
            return node
        for child in node.query_tree().children:
            found = find(child)
            if found is not None:
                return found
        return None

    conn = display.Display()
    try:
        hud = find(conn.screen().root)
        assert hud is not None
        return list(hud.shape_get_rectangles(shape.SK.Input).rectangles)
    finally:
        conn.close()


# --- the event stream delivers at once (WebKit holds a chunk until a later one arrives) ----------


def test_should_follow_a_quiet_event_with_a_flush_comment_soon() -> None:
    async def scenario() -> list[str]:
        server = HudServer(keepalive_s=30)
        await server.start()
        try:
            async with stream(server) as lines:
                await server.publish(HudEvent("listening", "Listening..."))
                seen: list[str] = []
                async with asyncio.timeout(2):  # far below the 30 s keepalive
                    while ":" not in seen:
                        line = await anext(lines)
                        if line:
                            seen.append(line)
                return seen
        finally:
            await server.close()

    seen = asyncio.run(scenario())
    assert seen[0].startswith("data: ") and seen[-1] == ":"


def test_should_replay_an_open_card_to_a_page_that_connects_late() -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        server = HudServer()
        await server.start()
        try:
            await server.publish(HudEvent("confirm", "Close window Firefox?", {"kind": "voice"}))
            async with stream(server) as lines:
                replayed = await next_event(lines)
            await server.publish(HudEvent("confirm", "", {"closed": True}))
            async with stream(server) as lines:
                await server.publish(HudEvent("idle"))
                later = await next_event(lines)  # the closed card is not replayed first
            return replayed, later
        finally:
            await server.close()

    replayed, later = asyncio.run(scenario())
    assert (replayed["state"], replayed["text"]) == ("confirm", "Close window Firefox?")
    assert later["state"] == "idle"
