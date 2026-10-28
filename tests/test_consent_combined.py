"""FR-CON-19: when consent and confirmation are both due, one question asks for both."""

import asyncio
from pathlib import Path
from typing import Literal

import pytest

from jarvis.config import ConsentSettings
from jarvis.confirm import HudAnswer
from jarvis.confirm.consent_question import CLICK_TO_ALLOW
from jarvis.consent.broker import Broker, TurnAsker
from jarvis.consent.session import SessionGrants
from jarvis.consent.store import GrantStore
from jarvis.policy import Tier
from jarvis.policy.decision import ToolCall, TurnContext
from jarvis.policy.gated import gated_dispatch
from tests.gated_rig import Confirmer, Impl, clean_state, dispatch, tool  # noqa: F401
from tests.test_consent_question import Rig, press, say

SEND = ("messages.teams:write",)


class AskingBroker:
    """Stands in for a broker that asked the user, who said yes (or was already granted)."""

    def __init__(self, result: Literal["granted", "denied"], *, asked: bool) -> None:
        self.result = result
        self.asked = asked
        self.seen: list[tuple[str, object]] = []

    async def require(
        self, scopes: tuple[str, ...], reason: str, ctx: TurnContext
    ) -> Literal["granted", "denied"]:
        self.seen.append((ctx.combined.action, ctx.combined.kind))
        if self.asked and self.result == "granted":
            ctx.combined.confirmed_by = "voice"
        return self.result


def test_should_take_the_consent_answer_as_the_confirmation() -> None:
    tool("t.send", Tier.T2, scopes=SEND, target_key="to")
    broker, confirmer = AskingBroker("granted", asked=True), Confirmer(yes=False)
    result, ctx, impl = dispatch(
        "t.send",
        {"to": "Rahul"},
        mode="balanced",
        consent=broker,
        confirmer=confirmer,
        heard=["send it to Rahul"],
    )
    assert result.error is None and len(impl.calls) == 1
    assert confirmer.asked == []  # one prompt only
    assert broker.seen == [("Send Rahul? This can't be undone.", "voice")]
    assert ctx.policy_decisions[0].confirmed_by == "voice"
    assert (ctx.combined.action, ctx.combined.kind, ctx.combined.confirmed_by) == ("", None, None)


def test_should_still_confirm_when_the_consent_was_already_held() -> None:
    tool("t.send", Tier.T2, scopes=SEND, target_key="to")
    confirmer = Confirmer(yes=True)
    _, _, impl = dispatch(
        "t.send",
        {"to": "Rahul"},
        mode="balanced",
        consent=AskingBroker("granted", asked=False),
        confirmer=confirmer,
    )
    assert len(confirmer.asked) == 1 and len(impl.calls) == 1


def test_should_not_confirm_after_a_consent_denial() -> None:
    tool("t.send", Tier.T2, scopes=SEND, target_key="to")
    confirmer = Confirmer(yes=True)
    result, _, impl = dispatch(
        "t.send",
        {"to": "Rahul"},
        mode="balanced",
        consent=AskingBroker("denied", asked=True),
        confirmer=confirmer,
    )
    assert result.error is not None and result.error.code == "CONSENT_DENIED"
    assert confirmer.asked == [] and impl.calls == []


# --- end to end: the real broker and the real question ------------------------------------------


def _send_through(
    tmp_path: Path, tier: Tier, script: object
) -> tuple[object, Rig, Impl, Confirmer]:
    tool("t.send", tier, scopes=SEND, target_key="to")
    settings = ConsentSettings(ask_timeout_s=2)
    broker = Broker(GrantStore(tmp_path / "g.json"), SessionGrants(), TurnAsker(settings), settings)
    impl, confirmer = Impl("t.send"), Confirmer(yes=False)

    async def main() -> tuple[object, Rig]:
        rig = Rig()
        ctx = TurnContext(
            "t1",
            mode="balanced",
            consent=broker,
            confirmer=confirmer,
            consent_question=rig.question,
            impls={"t.send": impl},
            heard=["send it to Rahul"],
        )
        running = asyncio.create_task(
            gated_dispatch(ToolCall("t.send", {"to": "Rahul"}, "brain"), ctx)
        )
        await script(rig)  # type: ignore[operator]
        return await asyncio.wait_for(running, 5), rig

    result, rig = asyncio.run(main())
    return result, rig, impl, confirmer


def test_should_ask_one_question_that_names_the_action_and_the_access(tmp_path: Path) -> None:
    _, rig, impl, confirmer = _send_through(tmp_path, Tier.T2, say("yes"))
    assert len(impl.calls) == 1 and confirmer.asked == []
    [spoken] = rig.speaker.said
    assert spoken.startswith("Send Rahul? This can't be undone. This lets me send your Teams")
    assert "Just this once, or always?" in spoken


def test_should_need_a_click_when_the_action_does(tmp_path: Path) -> None:
    script_steps = [say("yes"), press(HudAnswer("once", "button"))]

    async def script(rig: Rig) -> None:
        for step in script_steps:
            await step(rig)

    _, rig, impl, confirmer = _send_through(tmp_path, Tier.T3, script)
    assert len(impl.calls) == 1 and confirmer.asked == []
    assert rig.speaker.said[1] == CLICK_TO_ALLOW  # the spoken yes was not taken


@pytest.mark.parametrize("answer", [HudAnswer("y", "key"), HudAnswer("yes", "typed")])
def test_should_not_take_a_key_or_typing_for_a_click(tmp_path: Path, answer: HudAnswer) -> None:
    async def script(rig: Rig) -> None:
        await press(answer)(rig)
        await press(HudAnswer("no", "button"))(rig)

    _, _, impl, _ = _send_through(tmp_path, Tier.T3, script)
    assert impl.calls == []
