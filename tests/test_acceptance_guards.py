import asyncio
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from jarvis.activity import TurnRecord
from jarvis.contract import FinalResponse
from jarvis.desktop.x11 import WindowInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "acceptance_harness", ROOT / "scripts" / "acceptance_harness.py"
)
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
sys.modules["acceptance_harness"] = harness
spec.loader.exec_module(harness)


class FakeInnerBrain:
    def __init__(self) -> None:
        self.turn_calls = 0
        self.reset_calls = 0
        self.start_calls = 0
        self.close_calls = 0
        self.dispatch_calls = 0

    async def turn(self, envelope: Any, on_say: Any, on_ask: Any) -> FinalResponse:
        self.turn_calls += 1
        return FinalResponse(status="success", spoken="Done.", actions_taken=[])

    async def reset(self) -> None:
        self.reset_calls += 1

    async def start(self) -> None:
        self.start_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

    async def dispatch(self, policy_name: str, args: Any) -> None:
        self.dispatch_calls += 1


class StubHarness:
    def __init__(self, turns: list[TurnRecord]) -> None:
        self.log = StubLog(turns)
        self.rows: list[Any] = []
        self.say_called = False

    async def say(self, message: str) -> None:
        self.say_called = True
        raise AssertionError("must not be called")


class StubLog:
    def __init__(self, turns: list[TurnRecord]) -> None:
        self._turns = turns

    def turns(self) -> list[TurnRecord]:
        return self._turns


def test_should_return_true_when_wm_instance_is_gnome_calculator() -> None:
    window = WindowInfo(
        window_id=1,
        wm_instance="gnome-calculator",
        wm_class="Gnome-calculator",
        pid=None,
        title="Calculator",
    )
    assert harness.is_calculator(window) is True


def test_should_return_true_when_wm_class_is_org_gnome_calculator() -> None:
    window = WindowInfo(
        window_id=1,
        wm_instance="other",
        wm_class="org.gnome.Calculator",
        pid=None,
        title="Calculator",
    )
    assert harness.is_calculator(window) is True


def test_should_return_false_when_window_is_libreoffice_calc() -> None:
    window = WindowInfo(
        window_id=1,
        wm_instance="libreoffice",
        wm_class="libreoffice-calc",
        pid=None,
        title="Untitled 1 - LibreOffice Calc",
    )
    assert harness.is_calculator(window) is False


def test_should_return_false_when_window_is_gedit_with_calc_title() -> None:
    window = WindowInfo(
        window_id=1,
        wm_instance="gedit",
        wm_class="Gedit",
        pid=None,
        title="calc notes.txt",
    )
    assert harness.is_calculator(window) is False


def test_should_return_turn_ran_when_ran_is_true() -> None:
    result = harness.judge_dropped(ran=True, calculator_open=False, records=[])
    assert result == "a turn ran"


def test_should_return_calculator_opened_when_calculator_open_is_true() -> None:
    result = harness.judge_dropped(ran=False, calculator_open=True, records=[])
    assert result == "Calculator opened"


def test_should_return_never_heard_when_records_are_empty() -> None:
    result = harness.judge_dropped(ran=False, calculator_open=False, records=[])
    assert result is not None
    assert "never heard" in result


def test_should_return_not_first_word_rule_when_drop_reason_is_empty_transcript() -> None:
    record = TurnRecord(
        ts=datetime(2026, 10, 14, tzinfo=UTC),
        turn_id="t",
        raw_transcript="x",
        command="",
        route="dropped",
        drop_reason="empty transcript",
    )
    result = harness.judge_dropped(ran=False, calculator_open=False, records=[record])
    assert result is not None
    assert "not the first-word rule" in result


def test_should_return_none_when_drop_reason_is_first_word_drop() -> None:
    record = TurnRecord(
        ts=datetime(2026, 10, 14, tzinfo=UTC),
        turn_id="t",
        raw_transcript="x",
        command="",
        route="dropped",
        drop_reason=harness.FIRST_WORD_DROP,
    )
    result = harness.judge_dropped(ran=False, calculator_open=False, records=[record])
    assert result is None


def test_should_return_none_when_last_dropped_record_is_first_word_drop() -> None:
    record1 = TurnRecord(
        ts=datetime(2026, 10, 14, tzinfo=UTC),
        turn_id="t1",
        raw_transcript="x",
        command="",
        route="dropped",
        drop_reason="empty transcript",
    )
    record2 = TurnRecord(
        ts=datetime(2026, 10, 14, tzinfo=UTC),
        turn_id="t2",
        raw_transcript="x",
        command="",
        route="dropped",
        drop_reason=harness.FIRST_WORD_DROP,
    )
    result = harness.judge_dropped(ran=False, calculator_open=False, records=[record1, record2])
    assert result is None


def test_should_refuse_turn_when_gate_is_closed() -> None:
    asyncio.run(_test_should_refuse_turn_when_gate_is_closed())


async def _test_should_refuse_turn_when_gate_is_closed() -> None:
    inner = FakeInnerBrain()
    gate = harness.BrainGate(inner)
    envelope = MagicMock()
    response = await gate.turn(envelope, None, None)
    assert inner.turn_calls == 0
    assert gate.refused == 1
    assert response.status == "failed"


def test_should_let_turn_through_when_gate_is_open() -> None:
    asyncio.run(_test_should_let_turn_through_when_gate_is_open())


async def _test_should_let_turn_through_when_gate_is_open() -> None:
    inner = FakeInnerBrain()
    gate = harness.BrainGate(inner)
    gate.open = True
    envelope = MagicMock()
    response = await gate.turn(envelope, None, None)
    assert inner.turn_calls == 1
    assert gate.turns == 1
    assert response.status == "success"


def test_should_refuse_sixth_turn_when_limit_is_five() -> None:
    asyncio.run(_test_should_refuse_sixth_turn_when_limit_is_five())


async def _test_should_refuse_sixth_turn_when_limit_is_five() -> None:
    inner = FakeInnerBrain()
    gate = harness.BrainGate(inner, limit=5)
    gate.open = True
    envelope = MagicMock()
    for _ in range(5):
        await gate.turn(envelope, None, None)
    response = await gate.turn(envelope, None, None)
    assert inner.turn_calls == 5
    assert gate.refused == 1
    assert response.status == "failed"


def test_should_delegate_reset_when_reset_is_called() -> None:
    asyncio.run(_test_should_delegate_reset_when_reset_is_called())


async def _test_should_delegate_reset_when_reset_is_called() -> None:
    inner = FakeInnerBrain()
    gate = harness.BrainGate(inner)
    await gate.reset()
    assert inner.reset_calls == 1


def test_should_append_fail_skipped_row_when_max_brain_turns_reached() -> None:
    asyncio.run(_test_should_append_fail_skipped_row_when_max_brain_turns_reached())


async def _test_should_append_fail_skipped_row_when_max_brain_turns_reached() -> None:
    records = [
        TurnRecord(
            ts=datetime(2026, 10, 14, tzinfo=UTC),
            turn_id=f"t{i}",
            raw_transcript="x",
            command="",
            route="brain",
        )
        for i in range(5)
    ]
    stub = StubHarness(records)

    async def check(_record: TurnRecord) -> None:
        return None

    await harness.turn_case(stub, "brain-open", 1, "fx", "brain", check)
    assert len(stub.rows) == 1
    assert stub.rows[0].outcome.startswith("FAIL: skipped")
    assert stub.say_called is False
