"""R83 / FR-SAFE-03: a T2+ target the user did not say is confirmed, in every mode."""

import asyncio

import pytest

from jarvis.policy import Tier
from jarvis.policy.decision import ToolCall, TurnContext
from jarvis.policy.gated import gated_dispatch
from jarvis.policy.model import ToolSpec
from jarvis.policy.ports import NoConfirmer
from jarvis.policy.provenance import foreign_values, user_provided
from tests.gated_rig import (  # noqa: F401
    Confirmer,
    Consent,
    Impl,
    clean_state,
    dispatch,
    tool,
)

HEARD = ["Jarvis, send hi to Rahul Sharma", "send hi to rahul sharma"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Rahul Sharma", True),
        ("rahul", True),
        ("RAHUL SHARMA!", True),
        ("x@evil.com", False),
        ("Rahul Sharma and x@evil.com", False),  # 2 of 5 words: well under 80 %
        ("", True),
        ("...", True),
    ],
)
def test_should_count_a_value_as_the_users_only_when_they_said_its_words(
    value: str, expected: bool
) -> None:
    assert user_provided(value, HEARD) is expected


def test_should_check_the_declared_keys_or_else_the_target() -> None:
    declared = ToolSpec("t.send", Tier.T2, provenance_keys=("to", "text"))
    args = {"to": ["Rahul", "x@evil.com"], "text": "hi", "note": "anything"}
    assert foreign_values(declared, args, HEARD) == ["x@evil.com"]
    target_only = ToolSpec("t.trash", Tier.T2, target_key="path")
    assert foreign_values(target_only, {"path": "~/Secrets"}, HEARD) == ["~/Secrets"]
    assert foreign_values(ToolSpec("t.x", Tier.T2), {"path": "~/Secrets"}, HEARD) == []


def _send(mode: str, to: str, **kw: object) -> tuple[Confirmer, object, Impl]:
    tool("t.send", Tier.T2, provenance_keys=("to", "text"), **kw)
    confirmer = Confirmer(yes=True)
    args = {"to": to, "text": "hi"}
    result, _, impl = dispatch("t.send", args, mode=mode, confirmer=confirmer, heard=list(HEARD))
    return confirmer, result, impl


def test_should_run_the_users_own_target_in_yolo_without_asking() -> None:
    confirmer, _, impl = _send("yolo", "Rahul Sharma")
    assert confirmer.asked == [] and len(impl.calls) == 1


def test_should_ask_in_yolo_when_the_target_came_from_what_was_read() -> None:
    confirmer, _, impl = _send("yolo", "x@evil.com")
    [(prompt, kind, _)] = confirmer.asked
    assert kind == "voice"
    assert prompt.startswith("You didn't say 'x@evil.com': it came from something I read.")
    assert len(impl.calls) == 1  # the user said yes


def test_should_refuse_a_read_target_when_nothing_can_ask() -> None:
    tool("t.send", Tier.T2, provenance_keys=("to",))
    result, _, impl = dispatch(
        "t.send", {"to": "x@evil.com"}, mode="yolo", confirmer=NoConfirmer(), heard=list(HEARD)
    )
    assert result.error is not None and impl.calls == []


def test_should_keep_a_stronger_kind_and_add_the_note() -> None:
    tool("t.wipe", Tier.T3, target_key="path")
    confirmer = Confirmer(yes=True)
    dispatch("t.wipe", {"path": "~/Work"}, mode="balanced", confirmer=confirmer, heard=["hi"])
    [(prompt, kind, _)] = confirmer.asked
    assert kind == "click" and prompt.startswith("You didn't say '~/Work'")


def test_should_confirm_after_consent_in_yolo_when_scoped() -> None:
    tool("t.send", Tier.T2, scopes=("messages.teams:write",), provenance_keys=("to",))
    confirmer, consent = Confirmer(yes=False), Consent("granted")
    _, _, impl = dispatch(
        "t.send",
        {"to": "x@evil.com"},
        mode="yolo",
        confirmer=confirmer,
        consent=consent,
        heard=list(HEARD),
    )
    assert consent.asked and confirmer.asked and impl.calls == []


def test_should_leave_t1_tools_and_the_fast_path_alone() -> None:
    tool("t.focus", Tier.T1, target_key="ref")
    confirmer = Confirmer(yes=False)
    _, _, impl = dispatch("t.focus", {"ref": "Evil"}, mode="yolo", confirmer=confirmer)
    assert confirmer.asked == [] and len(impl.calls) == 1

    tool("t.send2", Tier.T2, provenance_keys=("to",))
    impl2 = Impl("t.send2")
    ctx = TurnContext("turn-1", mode="yolo", confirmer=confirmer, impls={"t.send2": impl2})
    asyncio.run(gated_dispatch(ToolCall("t.send2", {"to": "x@evil.com"}, "fastpath"), ctx))
    assert confirmer.asked == [] and len(impl2.calls) == 1  # the fast path is the user's words
