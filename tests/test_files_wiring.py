"""The file tools reach the brain (FR-PC-08), and "Jarvis, undo that" (FR-SAFE-05, §6.5)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from jarvis.activity import ActivityLog
from jarvis.brain.clock import TurnClock
from jarvis.brain.dispatch import TurnHooks, TurnTools
from jarvis.brain.failures import ToolError
from jarvis.brain.file_tools import call_files
from jarvis.config import Settings
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.turns import TurnRunner, TurnServices
from jarvis.orchestrator.voice import Voice
from jarvis.orchestrator.windows import Windows
from jarvis.policy import ToolCall, TurnContext
from jarvis.policy.decide import decide
from jarvis.undo import NOTHING_TO_UNDO, UndoLog, is_undo, run_undo
from tests.fastpath_fakes import FakeDesktop
from tests.gated_rig import Confirmer
from tests.orchestrator_rig import FakeSpeaker, command
from tests.test_files import home, service  # noqa: F401 - the fixture and the service rig


class FakeFiles:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def _rec(self, *call: object) -> dict[str, object]:
        self.calls.append(call)
        return {"ok": True}

    async def search_files(
        self, query: str, folder: str = "~", when: str | None = None, kind: str | None = None
    ) -> dict[str, object]:
        return await self._rec("search", query, folder, when, kind)

    async def open_file(self, path: str) -> dict[str, object]:
        return await self._rec("open", path)

    async def reveal(self, path: str) -> dict[str, object]:
        return await self._rec("reveal", path)

    async def trash(self, paths: list[str], contents: bool = False) -> dict[str, object]:
        return await self._rec("trash", paths, contents)

    async def delete_permanently(self, paths: list[str]) -> dict[str, object]:
        return await self._rec("delete", paths)

    async def move(self, paths: list[str], dest: str) -> dict[str, object]:
        return await self._rec("move", paths, dest)

    async def rename(self, path: str, name: str) -> dict[str, object]:
        return await self._rec("rename", path, name)

    async def copy(self, paths: list[str], dest: str) -> dict[str, object]:
        return await self._rec("copy", paths, dest)

    async def zip(self, paths: list[str], dest: str) -> dict[str, object]:
        return await self._rec("zip", paths, dest)


@pytest.mark.parametrize(
    ("name", "args", "call"),
    [
        (
            "files.search",
            {"query": "invoice", "kind": "pdf"},
            ("search", "invoice", "~", None, "pdf"),
        ),
        ("files.open", {"path": "~/a.txt"}, ("open", "~/a.txt")),
        (
            "files.trash",
            {"paths": ["~/Downloads"], "contents": True},
            ("trash", ["~/Downloads"], True),
        ),
        ("files.move", {"paths": ["~/a"], "dest": "~/b"}, ("move", ["~/a"], "~/b")),
        ("files.rename", {"path": "~/a", "name": "b"}, ("rename", "~/a", "b")),
        ("files.zip", {"paths": ["~/a"], "dest": "~/a.zip"}, ("zip", ["~/a"], "~/a.zip")),
    ],
)
def test_should_route_valid_file_calls(
    name: str, args: dict[str, Any], call: tuple[object, ...]
) -> None:
    files = FakeFiles()
    asyncio.run(call_files(files, name, args))
    assert files.calls == [call]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("files.search", {"query": ""}),
        ("files.search", {"query": "x", "when": "someday"}),
        ("files.trash", {"paths": []}),
        ("files.trash", {"paths": ["~/a"], "contents": "yes"}),
        ("files.move", {"paths": ["~/a"]}),
        ("files.open", {"path": "bad\x00path"}),
        ("files.rename", {"path": "~/a", "name": "b", "extra": 1}),
        ("files.nope", {}),
    ],
)
def test_should_refuse_bad_file_calls(name: str, args: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        asyncio.run(call_files(FakeFiles(), name, args))


def test_should_turn_file_errors_into_tool_errors_with_their_code(home: Path) -> None:  # noqa: F811
    files, _, _ = service(home)
    with pytest.raises(ToolError, match=r"^NOT_FOUND"):
        asyncio.run(call_files(files, "files.trash", {"paths": ["~/missing"]}))


def test_should_route_files_through_the_turns_tools() -> None:
    async def say(text: str) -> None:
        return None

    async def ask(question: str, options: list[str]) -> str:
        return ""

    files = FakeFiles()
    hooks = TurnHooks(say, ask, lambda final: None, TurnClock())
    tools = TurnTools("t1", hooks, object(), 5, files=files)  # type: ignore[arg-type]
    asyncio.run(tools("files.open", {"path": "~/a"}))
    assert files.calls == [("open", "~/a")]


# --- §6.5 ----------------------------------------------------------------------------------------


def test_should_trash_without_asking_in_yolo_but_guard_permanent_delete() -> None:
    trash = decide(
        ToolCall("files.trash", {"paths": ["~/Downloads"]}, "brain"), "yolo", TurnContext("t")
    )
    assert trash.action == "run"
    gone = ToolCall("files.delete_permanently", {"paths": ["~/Downloads"]}, "brain")
    assert decide(gone, "yolo", TurnContext("t")).kind == "guardrail"


@pytest.mark.parametrize(
    ("text", "undo"),
    [
        ("undo", True),
        ("Jarvis, undo that", True),
        ("undo it please", True),
        ("Hey Jarvis, undo the last thing", True),
        ("undo my changes in the doc", False),
        ("open undo manager", False),
    ],
)
def test_should_recognise_undo(text: str, undo: bool) -> None:
    assert is_undo(text) is undo


def test_should_undo_the_trash_from_a_turn(home: Path, tmp_path: Path) -> None:  # noqa: F811
    log = UndoLog()
    files, _, _ = service(home, log)
    asyncio.run(files.trash(["~/Downloads"], contents=True))
    speaker = FakeSpeaker()

    async def hud(event: object) -> None:
        return None

    services = TurnServices(
        settings=Settings(),
        mode="yolo",
        desktop=FakeDesktop([]),
        brain=None,
        voice=Voice(speaker, Timing(deaf_tail_s=0.0)),
        hud=hud,
        activity=ActivityLog(directory=tmp_path / "activity"),
        timing=Timing(deaf_tail_s=0.0),
        windows=Windows(),
        trace=ToolTrace(),
        undo=log,
    )
    asyncio.run(TurnRunner(services).run(command("undo that", None)))
    assert speaker.said == ["Put 3 items back in Downloads."]
    assert len(list((home / "Downloads").iterdir())) == 3


def test_should_say_when_there_is_nothing_to_undo_and_confirm_in_safe_mode() -> None:
    log = UndoLog()
    final = asyncio.run(run_undo(log, TurnContext("t", mode="balanced")))
    assert final.spoken == NOTHING_TO_UNDO
    confirmer = Confirmer(yes=False)
    final = asyncio.run(run_undo(log, TurnContext("t", mode="safe", confirmer=confirmer)))
    assert confirmer.asked and final.status == "cancelled"
