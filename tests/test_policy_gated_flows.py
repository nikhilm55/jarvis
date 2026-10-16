"""gated_dispatch asks the user: confirmation kinds, consent, and every way they say no."""

import asyncio
from typing import Any

import pytest

from jarvis.config import PolicySettings
from jarvis.policy import Tier
from jarvis.policy.decision import ToolCall, TurnContext
from jarvis.policy.gated import MISMATCHED_IMPL_REASON, gated_dispatch
from jarvis.policy.lists import UNRESOLVABLE_REASON
from jarvis.policy.ports import Answer, Method
from tests.gated_rig import (  # noqa: F401
    Confirmer,
    Consent,
    Impl,
    clean_state,
    dispatch,
    records,
    tool,
)


def test_should_run_when_the_user_confirms_and_audit_who_confirmed() -> None:
    tool("t.app", Tier.T2)
    confirmer = Confirmer(yes=True, method="button")
    result, ctx, impl = dispatch("t.app", mode="balanced", confirmer=confirmer)
    assert result.error is None
    assert len(impl.calls) == 1
    assert [(k, p) for p, k, _ in confirmer.asked] == [("voice", "Run t.app?")]
    assert records()[0]["confirmed_by"] == "button"
    assert ctx.policy_decisions[0].confirmed_by == "button"


@pytest.mark.parametrize(
    ("yes", "method", "code", "why"),
    [
        (False, "voice", "CANCELLED", "you declined"),
        (False, "timeout", "BLOCKED_BY_POLICY", "no answer to the confirmation"),
    ],
)
def test_should_refuse_when_the_user_says_no_or_does_not_answer(
    yes: bool, method: Method, code: str, why: str
) -> None:
    tool("t.app", Tier.T2)
    result, _, impl = dispatch("t.app", mode="balanced", confirmer=Confirmer(yes, method))
    assert result.error is not None
    assert (result.error.code, result.error.why) == (code, why)
    assert impl.calls == []


def test_should_ask_for_a_click_with_the_target_phrase_when_t3_in_yolo() -> None:
    tool("t.wipe", Tier.T3)
    confirmer = Confirmer(yes=True)
    dispatch("t.wipe", {"path": "/data/old-photos/"}, mode="yolo", confirmer=confirmer)
    asked = [(k, phrase) for _, k, phrase in confirmer.asked]
    assert asked == [("guardrail", "confirm wipe /data/old-photos")]
    confirmer = Confirmer(yes=True)
    dispatch("t.wipe", {"path": "/data/old-photos"}, mode="safe", confirmer=confirmer)
    assert [(k, phrase) for _, k, phrase in confirmer.asked] == [("click", None)]


def test_should_refuse_when_consent_is_denied_and_by_default() -> None:
    tool("t.files", Tier.T0, scopes=("files.documents:read",))
    result, _, impl = dispatch("t.files", mode="balanced")
    assert result.error is not None
    assert (result.error.code, result.error.why) == ("CONSENT_DENIED", "consent denied")
    consent = Consent("denied")
    result, _, impl2 = dispatch("t.files", mode="safe", consent=consent)
    assert result.error is not None
    assert consent.asked == [("files.documents:read",)]
    assert impl.calls == impl2.calls == []


def test_should_run_after_consent_and_ask_the_confirmation_that_is_still_due() -> None:
    tool("t.files", Tier.T1, scopes=("files.documents:read",))
    consent, confirmer = Consent("granted"), Confirmer(yes=True)
    result, _, impl = dispatch("t.files", mode="safe", consent=consent, confirmer=confirmer)
    assert result.error is None
    assert len(impl.calls) == 1
    assert len(confirmer.asked) == 1
    tool("t.files0", Tier.T0, scopes=("files.documents:read",))
    confirmer = Confirmer(yes=False)
    result, _, impl = dispatch("t.files0", mode="balanced", consent=consent, confirmer=confirmer)
    assert result.error is None
    assert confirmer.asked == []


def test_should_refuse_when_the_confirmer_itself_fails() -> None:
    class Broken:
        async def ask(self, *args: object, **kwargs: object) -> Answer:
            raise RuntimeError("hud gone")

    tool("t.app", Tier.T2)
    result, _, impl = dispatch("t.app", mode="balanced", confirmer=Broken())
    assert result.error is not None
    assert result.error.why == "policy error: RuntimeError"
    assert impl.calls == []


def phrase_asked(name: str, args: dict[str, object], **spec: Any) -> str | None:
    tool(name, Tier.T3, **spec)
    confirmer = Confirmer(yes=True)
    dispatch(name, args, mode="yolo", confirmer=confirmer)
    [(_, kind, phrase)] = confirmer.asked
    assert kind == "guardrail"
    return phrase


@pytest.mark.parametrize(
    ("cmd", "words"),
    [
        ("rm -rf ~/Downloads/old", ("confirm", "rm", "~/Downloads/old")),
        ("sudo rm -rf /var/lib/x/", ("confirm", "sudo", "/var/lib/x")),
        ("cd ~/p && rm -rf build dist", ("confirm", "rm", "dist")),
        ("FOO=1 mkfs.ext4 /dev/sdb1", ("confirm", "mkfs.ext4", "/dev/sdb1")),
        ("shutdown -h now", ("confirm", "shutdown", "now")),
    ],
)
def test_should_name_the_verb_and_the_target_when_yolo_confirms_a_shell_command(
    cmd: str, words: tuple[str, ...]
) -> None:
    phrase = phrase_asked("t.shell", {"cmd": cmd})
    assert phrase == " ".join(words)


def test_should_take_the_target_from_the_tools_declared_key_else_its_last_path() -> None:
    declared = phrase_asked(
        "t.delete_file", {"note": "x", "item": "~/Pictures/trip.jpg"}, target_key="item"
    )
    assert declared == "confirm delete file ~/Pictures/trip.jpg"
    assert phrase_asked("t.erase", {"src": "a", "dst": "~/b/"}) == "confirm erase ~/b"
    assert phrase_asked("t.reset", {}) == "confirm reset"


@pytest.mark.parametrize("yes", ["no", "yes", 1, None])
def test_should_not_run_when_the_answer_is_truthy_but_not_a_yes(yes: Any) -> None:
    tool("t.app", Tier.T2)
    confirmer = Confirmer()
    confirmer.answer = Answer(yes, "voice")
    result, _, impl = dispatch("t.app", mode="balanced", confirmer=confirmer)
    assert result.error is not None
    assert impl.calls == []


def test_should_audit_the_scopes_the_call_was_judged_on() -> None:
    tool("t.files", Tier.T1, scopes=("files.documents:read", "files.desktop:write"))
    dispatch("t.files", mode="balanced", consent=Consent("granted"))
    [decision, _] = records()
    assert decision["scopes"] == "files.desktop:write,files.documents:read"
    tool("t.plain", Tier.T0)
    dispatch("t.plain", mode="balanced")
    assert records()[-2]["scopes"] == ""


def test_should_refuse_an_impl_filed_under_another_tools_name() -> None:
    tool("t.read", Tier.T0)
    tool("t.wipe", Tier.T3)
    cheap = Impl("t.read")  # registered for the T0 tool ...
    ctx = TurnContext("turn-1", mode="yolo", impls={"t.wipe": cheap})  # ... filed under the T3 one
    result = asyncio.run(gated_dispatch(ToolCall("t.wipe", {}, "brain"), ctx))
    assert result.error is not None
    assert result.error.why == MISMATCHED_IMPL_REASON
    assert cheap.calls == []
    assert records()[0]["decision"] == "deny"
    unnamed = TurnContext("turn-2", mode="yolo", impls={"t.read": Impl("")})
    result = asyncio.run(gated_dispatch(ToolCall("t.read", {}, "brain"), unnamed))
    assert result.error is not None
    assert result.error.why == MISMATCHED_IMPL_REASON


def test_should_say_to_spell_the_path_out_when_the_deny_list_cannot_trace_a_call() -> None:
    tool("t.shell", Tier.T2)
    settings = PolicySettings(deny_paths=["~/secrets"])
    result, _, impl = dispatch("t.shell", {"cmd": "cd ~/x && ls"}, mode="yolo", settings=settings)
    assert result.error is not None
    assert result.error.why == UNRESOLVABLE_REASON
    assert "exact path" in result.error.remedy[0]
    assert impl.calls == []
