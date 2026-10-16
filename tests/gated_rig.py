"""A rig for gated_dispatch tests: a recording tool, fake ports, and the audit log reader."""

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any, Literal

import pytest

from jarvis import paths
from jarvis.policy import Tier, ToolSpec, registry
from jarvis.policy.decision import Kind, ToolCall, TurnContext
from jarvis.policy.gated import ToolResult, gated_dispatch
from jarvis.policy.ports import Answer, Method


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    logger = logging.getLogger("jarvis.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


class Impl:
    """A tool implementation that records its calls."""

    def __init__(self, name: str = "", error: Exception | None = None) -> None:
        self.tool_name = name  # what @tool_impl("…") records on a real implementation
        self.calls: list[Mapping[str, object]] = []
        self.audit_at_call: list[dict[str, Any]] = []
        self.error = error

    async def __call__(self, args: Mapping[str, object]) -> object:
        self.calls.append(args)
        self.audit_at_call = records()
        if self.error is not None:
            raise self.error
        return {"done": True}


class Confirmer:
    def __init__(self, yes: bool = True, method: Method = "voice") -> None:
        self.answer = Answer(yes, method)
        self.asked: list[tuple[str, Kind, str | None]] = []

    async def ask(
        self, prompt: str, kind: Kind, target_phrase: str | None = None, timeout_s: float = 15
    ) -> Answer:
        self.asked.append((prompt, kind, target_phrase))
        return self.answer


class Consent:
    def __init__(self, result: Literal["granted", "denied"]) -> None:
        self.result = result
        self.asked: list[tuple[str, ...]] = []

    async def require(
        self, scopes: tuple[str, ...], reason: str, ctx: TurnContext
    ) -> Literal["granted", "denied"]:
        self.asked.append(scopes)
        return self.result


def records() -> list[dict[str, Any]]:
    log = paths.data_dir() / "logs" / "audit.jsonl"
    if not log.exists():
        return []
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r.get("name") == "jarvis.policy"]


def dispatch(
    name: str, args: Mapping[str, object] | None = None, **ctx_fields: Any
) -> tuple[ToolResult, TurnContext, Impl]:
    impl = ctx_fields.pop("impl", None) or Impl()
    impl.tool_name = impl.tool_name or name
    ctx = TurnContext("turn-1", impls={name: impl}, **ctx_fields)
    result = asyncio.run(gated_dispatch(ToolCall(name, args or {}, "brain"), ctx))
    return result, ctx, impl


def tool(name: str, tier: Tier, **kw: Any) -> None:
    registry.register(ToolSpec(name, tier, **kw))
