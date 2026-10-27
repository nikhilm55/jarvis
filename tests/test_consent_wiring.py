"""Tests for the consent wiring: gate, turn runner, and orchestrator."""

import asyncio
import dataclasses
from pathlib import Path

import pytest

import jarvis.fastpath.executor
import jarvis.mcp.tools  # noqa: F401
from jarvis import paths
from jarvis.brain.dispatch import OnAsk, OnSay
from jarvis.config import ConsentSettings, Settings
from jarvis.consent.broker import Broker, build_consent
from jarvis.consent.scope import Scope, ScopeError, parse_scopes
from jarvis.consent.session import SessionGrants
from jarvis.contract import FinalResponse
from jarvis.orchestrator import assemble
from jarvis.orchestrator.core import Orchestrator
from jarvis.orchestrator.timing import Timing
from jarvis.orchestrator.trace import ToolTrace
from jarvis.orchestrator.turns import TurnRunner
from jarvis.policy import Tier, registry
from jarvis.policy.decision import TurnContext
from tests.consent_rig import TEAMS_R, ScriptedAsker, make_rig, says
from tests.core_rig import CoreRig
from tests.gated_rig import Impl, dispatch, tool
from tests.listener_rig import seg
from tests.orchestrator_rig import FakeBrain, command, until
from tests.orchestrator_rig import make_rig as make_turn_rig


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


def test_consent_denied_single_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "voice"))
    tool("t.teams", Tier.T0, scopes=("messages.teams:read",))
    impl = Impl("t.teams")
    result, _, _ = dispatch(
        "t.teams",
        {},
        mode="balanced",
        consent=rig.broker,
        impl=impl,
    )
    assert result.error is not None
    assert result.error.code == "CONSENT_DENIED"
    assert impl.calls == []
    assert result.error.remedy == [
        "Say 'Jarvis, allow teams', or turn it on in Settings → Permissions."
    ]


def test_consent_denied_multiple_scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "voice"))
    tool("t.multi", Tier.T0, scopes=("messages.teams:read", "messages.teams:write", "screen:read"))
    impl = Impl("t.multi")
    result, _, _ = dispatch(
        "t.multi",
        {},
        mode="balanced",
        consent=rig.broker,
        impl=impl,
    )
    assert result.error is not None
    assert result.error.code == "CONSENT_DENIED"
    assert impl.calls == []
    allow = "'Jarvis, allow screen' or 'Jarvis, allow teams'"
    assert result.error.remedy == [f"Say {allow}, or turn it on in Settings → Permissions."]


def test_consent_granted_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("once", "voice"))
    tool("t.teams", Tier.T0, scopes=("messages.teams:read",))
    impl = Impl("t.teams")
    result, _, _ = dispatch(
        "t.teams",
        {},
        mode="balanced",
        consent=rig.broker,
        impl=impl,
    )
    assert result.error is None
    assert result.output == {"done": True}
    assert len(impl.calls) == 1


def test_yolo_never_grant_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "voice"))
    rig.store.grant(Scope.parse("messages.teams:read"), "never", "voice")
    tool("t.teams", Tier.T0, scopes=("messages.teams:read",))
    impl = Impl("t.teams")
    result, _, _ = dispatch(
        "t.teams",
        {},
        mode="yolo",
        consent=rig.broker,
        impl=impl,
    )
    assert result.error is not None
    assert result.error.code == "CONSENT_DENIED"
    assert impl.calls == []


def test_yolo_auto_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "voice"))
    tool("t.teams", Tier.T0, scopes=("messages.teams:read",))
    impl = Impl("t.teams")
    result, _, _ = dispatch(
        "t.teams",
        {},
        mode="yolo",
        consent=rig.broker,
        impl=impl,
    )
    assert result.error is None
    assert result.output == {"done": True}
    assert len(impl.calls) == 1
    assert rig.checks()[-1]["reason"] == "auto-allowed: YOLO"


def test_yolo_no_consent_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool("t.teams", Tier.T0, scopes=("messages.teams:read",))
    impl = Impl("t.teams")
    result, _, _ = dispatch(
        "t.teams",
        {},
        mode="yolo",
        impl=impl,
    )
    assert result.error is not None
    assert result.error.code == "CONSENT_DENIED"
    assert impl.calls == []


def test_yolo_no_scopes_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "voice"))
    tool("t.plain", Tier.T0)
    impl = Impl("t.plain")
    result, _, _ = dispatch(
        "t.plain",
        {},
        mode="yolo",
        consent=rig.broker,
        impl=impl,
    )
    assert result.error is None
    assert result.output == {"done": True}
    assert len(impl.calls) == 1
    assert rig.asker.asked == []


def test_all_registered_scopes_parse() -> None:
    assert len(registry._REGISTRY) > 5
    bad: list[str] = []
    for name, spec in registry._REGISTRY.items():
        try:
            parse_scopes(spec.scopes)
        except ScopeError:
            bad.append(name)
    assert not bad, f"Scopes do not parse for: {bad}"


def test_bad_scope_raises_scope_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool("t.bad", Tier.T0, scopes=("not a scope",))
    spec = registry.get("t.bad")
    assert spec is not None
    with pytest.raises(ScopeError):
        parse_scopes(spec.scopes)


def test_build_consent_denies_ungranted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consent = build_consent(ConsentSettings())
    ctx = TurnContext("t1", mode="balanced")
    result = asyncio.run(consent.broker.require(("messages.teams:read",), "to read", ctx))
    assert result == "denied"


def test_build_consent_grants_and_creates_file() -> None:
    asker = ScriptedAsker(says("always", "voice"))
    consent = build_consent(ConsentSettings(), asker=asker)
    ctx = TurnContext("t1", mode="balanced")
    result = asyncio.run(consent.broker.require(("messages.teams:read",), "to read", ctx))
    assert result == "granted"
    assert (paths.data_dir() / "grants.json").exists()


def test_tool_trace_consent_is_broker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("no", "voice"))
    trace = ToolTrace(consent=rig.broker)
    ctx = trace.turn_context()
    assert ctx.consent is rig.broker


def test_tool_trace_default_consent_denies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace = ToolTrace()
    ctx = trace.turn_context()
    result = asyncio.run(ctx.consent.require(("messages.teams:read",), "to read", ctx))
    assert result == "denied"


def test_turn_runner_consent_wiring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path, monkeypatch, says("once", "voice"), says("no", "voice"))
    records: list[tuple[str, str]] = []

    async def script(on_say: OnSay, on_ask: OnAsk) -> FinalResponse:
        ctx = turn.runner._s.trace.ctx
        assert ctx is not None
        assert ctx.consent is rig.broker
        records.append((ctx.turn_id, await rig.broker.require((TEAMS_R,), "to read", ctx)))
        if len(records) == 1:
            return FinalResponse(status="needs_input", spoken="Which one?", follow_up_expected=True)
        return FinalResponse(status="success", spoken="Done.")

    turn = make_turn_rig(tmp_path, FakeBrain(script=script))
    services = dataclasses.replace(turn.runner._s, consent=rig.broker, grants=rig.session)
    turn.runner = TurnRunner(services)

    async def scenario() -> None:
        task = asyncio.create_task(turn.runner.run(command("read teams", None)))
        try:
            await until(lambda: turn.windows.kind == "reply")
            assert turn.windows.offer_answer("the second one") is True
            await asyncio.wait_for(task, 5)
        finally:
            task.cancel()

    asyncio.run(scenario())

    assert [result for _, result in records] == ["granted", "granted"]
    assert len(rig.asker.asked) == 1  # the follow-up did not ask again
    assert records[0][0] != records[1][0]
    assert not rig.session.holds(Scope.parse(TEAMS_R), records[1][0])  # the command is over
    assert not rig.session.holds(Scope.parse(TEAMS_R), "new-turn-id")


def test_orchestrator_idle_reset_ends_grant(tmp_path: Path) -> None:
    async def scenario() -> None:
        grants = SessionGrants()
        grants.grant(Scope.parse(TEAMS_R), "session", "turn-1")
        assert grants.holds(Scope.parse(TEAMS_R), "turn-1")

        rig = CoreRig(
            tmp_path,
            ["Jarvis, what's the plan?"],
            timing=Timing(deaf_tail_s=0.0, inactivity_reset_s=0.05),
        )
        rig.parts.grants = grants
        rig.orchestrator = Orchestrator(
            Settings(),
            rig.parts,
            hud=rig._hud,
            activity=rig.orchestrator._activity,
            timing=Timing(deaf_tail_s=0.0, inactivity_reset_s=0.05),
        )

        assert rig.brain is not None
        run = asyncio.create_task(rig.orchestrator.run())
        try:
            rig.feed.push(seg())
            await asyncio.wait_for(rig.brain.reset_called.wait(), 5)
            rig.feed.end()
            await asyncio.wait_for(run, 10)
        finally:
            run.cancel()

        assert not grants.holds(Scope.parse(TEAMS_R), "turn-1")

    asyncio.run(scenario())


def test_build_components_wires_the_real_broker_with_no_asker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assemble, "_transcriber", lambda settings: object())
    monkeypatch.setattr(assemble, "_warm_engine", lambda settings: object())
    monkeypatch.setattr(assemble, "_segmenter", lambda settings, voice: object())
    monkeypatch.setattr(assemble, "Speaker", lambda *args, **kwargs: object())
    monkeypatch.setattr(assemble, "Voice", lambda *args, **kwargs: object())
    source = object()
    parts = asyncio.run(
        assemble.build_components(
            Settings(),
            source,  # type: ignore[arg-type]
            mode="balanced",
            with_brain=False,
        )
    )
    assert isinstance(parts.consent, Broker)
    assert isinstance(parts.grants, SessionGrants)
    ctx = TurnContext("t1", mode="balanced")
    assert asyncio.run(parts.consent.require((TEAMS_R,), "to read", ctx)) == "denied"  # NoAsker
    assert parts.trace.turn_context().consent is parts.consent
