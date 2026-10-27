"""The question a confirmation asks, in plain words (FR-SAFE-07), and FR-SAFE-05's undo note."""

from collections.abc import Iterator

import pytest

from jarvis.policy import registry
from jarvis.policy.model import Tier, ToolSpec
from jarvis.policy.prompts import NOT_UNDOABLE, describe


@pytest.fixture(autouse=True)
def tools() -> Iterator[None]:
    saved = dict(registry._REGISTRY)
    registry.register(ToolSpec("t.close_window", Tier.T1, target_key="ref"))
    registry.register(ToolSpec("t.trash", Tier.T2, undoable=True))
    registry.register(ToolSpec("t.delete_permanently", Tier.T3))
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


def test_should_name_the_verb_and_the_declared_target() -> None:
    assert describe("t.close_window", {"ref": "Firefox"}, Tier.T1) == "Close window Firefox?"


def test_should_fall_back_to_a_name_argument_then_the_paths() -> None:
    assert describe("t.close_window", {"name": "Notes"}, Tier.T1) == "Close window Notes?"
    question = describe("t.trash", {"paths": ["~/a", "~/b", "~/c", "~/d"]}, Tier.T2)
    assert question == "Trash ~/a, ~/b, ~/c and 1 more?"


def test_should_quote_a_shell_command_and_cut_a_long_one() -> None:
    assert describe("shell.run", {"cmd": "git push --force"}, Tier.T2) == (
        f"Run 'git push --force'? {NOT_UNDOABLE}"
    )
    long = describe("shell.run", {"cmd": "echo " + "x" * 200}, Tier.T1)
    assert long.startswith("Run 'echo x") and long.endswith("…'?") and len(long) < 100


@pytest.mark.parametrize(
    ("name", "tier", "note"),
    [
        ("t.delete_permanently", Tier.T3, True),
        ("t.trash", Tier.T2, False),  # declared undoable
        ("t.close_window", Tier.T1, False),  # T1 is low risk
        ("t.unknown", Tier.T2, True),  # an unknown tool is never assumed undoable
    ],
)
def test_should_say_up_front_when_an_action_cannot_be_undone(
    name: str, tier: Tier, note: bool
) -> None:
    assert describe(name, {"paths": ["~/x"]}, tier).endswith(NOT_UNDOABLE) is note
