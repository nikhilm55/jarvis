"""Managing consent by voice (FR-CON-13), on the fast path: no brain, no cloud.

"Jarvis, what can you access?" · "allow Teams" · "always allow my calendar" · "revoke Teams" /
"stop reading my email" · "forget all permissions". Each runs as a tool through
`gated_dispatch`: listing and revoking are T0 (they only ever reduce access), allowing for the
session is T1, and "always" is T2, so it is confirmed on the card where anyone can see it.
"""

import dataclasses
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from jarvis.config import PolicySettings
from jarvis.consent.scope import Scope
from jarvis.consent.wording import describe, source_name
from jarvis.contract import FinalResponse
from jarvis.policy import Tier, ToolSpec, register
from jarvis.policy.decision import ToolCall, TurnContext
from jarvis.policy.gated import gated_dispatch, tool_impl

__all__ = ["Allow", "ConsentAdmin", "ForgetAll", "ListAccess", "Revoke", "parse", "run"]

# Sources Jarvis knows by name before anything is granted (FRS 5.11.1).
KNOWN_SOURCES = (
    "messages.teams",
    "messages.slack",
    "messages.whatsapp",
    "email.outlook",
    "email.gmail",
    "calendar.outlook",
    "calendar.google",
    "contacts.m365",
    "screen",
    "clipboard",
    "browser.session",
    "notes.obsidian",
    "notifications",
    "meetings",
    "memory",
)
_CATEGORY_WORDS = {
    "messages": "messages",
    "message": "messages",
    "chats": "messages",
    "email": "email",
    "emails": "email",
    "mail": "email",
    "calendar": "calendar",
    "contacts": "contacts",
    "files": "files",
    "notes": "notes",
}


@dataclass(frozen=True)
class ListAccess:
    """ "What can you access?" """


@dataclass(frozen=True)
class Allow:
    """ "Allow Teams" (this session) or "always allow my calendar"."""

    words: str
    always: bool


@dataclass(frozen=True)
class Revoke:
    """ "Revoke Teams", "stop reading my email"."""

    words: str


@dataclass(frozen=True)
class ForgetAll:
    """ "Forget all permissions": everything asks again, "never" included."""


ManageIntent = ListAccess | Allow | Revoke | ForgetAll

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), kind)
    for pattern, kind in (
        (r"^what (?:can you|do you have) access(?: to)?$", "list"),
        (r"^what permissions do you have$", "list"),
        (r"^(?:forget|reset|clear) (?:all )?(?:my )?permissions$", "forget"),
        (r"^revoke (?:all|everything)$", "forget"),
        (r"^always allow (?:access to )?(?:my )?(?P<what>.+)$", "always"),
        (r"^allow (?:access to )?(?:my )?(?P<what>.+?)(?P<always> always)?$", "allow"),
        (r"^(?:revoke|block) (?:access to )?(?:my )?(?P<what>.+)$", "revoke"),
        (r"^stop (?:reading|using|accessing|touching) (?:my )?(?P<what>.+)$", "revoke"),
    )
)


def parse(text: str) -> ManageIntent | None:
    """The consent-management intent in `text`, or None."""
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    if words[:1] == ["jarvis"]:
        words = words[1:]
    if words[-1:] == ["please"]:
        words = words[:-1]
    said = " ".join(words)
    for pattern, kind in _PATTERNS:
        match = pattern.match(said)
        if match is None:
            continue
        if kind == "list":
            return ListAccess()
        if kind == "forget":
            return ForgetAll()
        what = match.group("what")
        if kind == "revoke":
            return Revoke(what)
        return Allow(what, always=kind == "always" or bool(match.groupdict().get("always")))
    return None


def resolve(words: str, extra: Iterable[str] = ()) -> list[str]:
    """The sources that `words` name: an app ("Teams"), a folder ("Documents") or a category."""
    candidates = sorted(set(KNOWN_SOURCES) | set(extra))
    said = set(words.split())
    named = [s for s in candidates if source_name(s).lower() in said or s in said]
    if named:
        return named
    categories = {_CATEGORY_WORDS[w] for w in said if w in _CATEGORY_WORDS}
    return [s for s in candidates if s.partition(".")[0] in categories or s in categories]


class ConsentAdmin(Protocol):
    """What the voice commands change: the broker's admin side, called only from the impls."""

    def access_overview(self) -> list[tuple[str, str]]: ...

    def known_sources(self) -> list[str]: ...

    async def voice_allow(
        self, scopes: tuple[Scope, ...], lifetime: Literal["session", "always"], ctx: TurnContext
    ) -> None: ...

    def voice_revoke(self, sources: set[str], ctx: TurnContext) -> list[str]: ...

    def voice_forget_all(self, ctx: TurnContext) -> None: ...


def _allow_tier(args: Mapping[str, object]) -> tuple[Tier, tuple[str, ...]]:
    return (Tier.T2 if args.get("always") is True else Tier.T1), ()


register(ToolSpec("consent.access_overview", Tier.T0))
register(ToolSpec("consent.voice_allow", Tier.T1, classify=_allow_tier, target_key="what"))
register(ToolSpec("consent.voice_revoke", Tier.T0))
register(ToolSpec("consent.voice_forget_all", Tier.T0))


def _speak_overview(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "I don't have access to any of your data yet. I'll ask first."
    by_state: dict[str, list[str]] = {}
    for scope, state in rows:
        by_state.setdefault(state, []).append(scope)
    parts = []
    if "always" in by_state:
        parts.append(f"I can always {describe(by_state['always'])}.")
    if "session" in by_state:
        parts.append(f"For this session I can {describe(by_state['session'])}.")
    if "never" in by_state:
        parts.append(f"You told me never to {describe(by_state['never'])}.")
    return " ".join(parts)


def _folders(settings: PolicySettings) -> list[str]:
    return sorted(set(settings.consent_folders.values()))


async def run(intent: ManageIntent, admin: ConsentAdmin, ctx: TurnContext) -> FinalResponse:
    """Carry out one consent-management command through the gate, and say what changed."""
    extra = _folders(ctx.settings) + admin.known_sources()
    call = _call(intent, extra)
    if isinstance(call, FinalResponse):
        return call
    sources = resolve(str(call.args.get("what", "")), extra)
    scopes = tuple(Scope(source, "read") for source in sources)
    lifetime: Literal["session", "always"] = "always" if call.args.get("always") else "session"
    reply: dict[str, object] = {}

    @tool_impl("consent.access_overview")
    async def overview(args: Mapping[str, object]) -> object:
        reply["rows"] = admin.access_overview()
        return "ok"

    @tool_impl("consent.voice_allow")
    async def allow(args: Mapping[str, object]) -> object:
        await admin.voice_allow(scopes, lifetime, ctx)
        return "ok"

    @tool_impl("consent.voice_revoke")
    async def revoke(args: Mapping[str, object]) -> object:
        reply["removed"] = admin.voice_revoke(set(sources), ctx)
        return "ok"

    @tool_impl("consent.voice_forget_all")
    async def forget_all(args: Mapping[str, object]) -> object:
        admin.voice_forget_all(ctx)
        return "ok"

    impls = {
        "consent.access_overview": overview,
        "consent.voice_allow": allow,
        "consent.voice_revoke": revoke,
        "consent.voice_forget_all": forget_all,
    }
    turn = dataclasses.replace(
        ctx, impls={call.name: impls[call.name]}
    )  # gate-ok: builds the impl table
    result = await gated_dispatch(call, turn)
    if result.error is not None:
        unchanged = "Okay, I'll leave the permissions as they are."
        return FinalResponse(status="cancelled", spoken=unchanged)
    return FinalResponse(status="success", spoken=_said(call.name, reply, scopes, lifetime))


def _said(name: str, reply: dict[str, object], scopes: tuple[Scope, ...], lifetime: str) -> str:
    if name == "consent.access_overview":
        rows = reply.get("rows")
        return _speak_overview(rows if isinstance(rows, list) else [])
    if name == "consent.voice_allow":
        when = "from now on" if lifetime == "always" else "for this session"
        return f"Okay, I can {describe(map(str, scopes))} {when}."
    if name == "consent.voice_revoke":
        removed = reply.get("removed")
        if isinstance(removed, list) and removed:
            return f"Okay, I won't {describe(removed)} any more."
        return "I had no access to that."
    return "Done. I'll ask again before touching any of your data."


def _call(intent: ManageIntent, extra: list[str]) -> ToolCall | FinalResponse:
    if isinstance(intent, ListAccess):
        return ToolCall("consent.access_overview", {}, "fastpath")
    if isinstance(intent, ForgetAll):
        return ToolCall("consent.voice_forget_all", {}, "fastpath")
    if not resolve(intent.words, extra):
        return FinalResponse(
            status="success",
            spoken=f"I don't know a source called {intent.words}. Try Teams, email or calendar.",
        )
    if isinstance(intent, Revoke):
        return ToolCall("consent.voice_revoke", {"what": intent.words}, "fastpath")
    args = {"what": intent.words, "always": intent.always}
    return ToolCall("consent.voice_allow", args, "fastpath")
