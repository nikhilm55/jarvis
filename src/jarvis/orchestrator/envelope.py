"""Builds the turn envelope the brain receives: STT info, OS facts, the user's name (R53)."""

import os
import platform
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime

from jarvis.config import Settings
from jarvis.contract import TurnEnvelope
from jarvis.contract.models import SttInfo, TurnContext, TurnPolicy, UserInfo
from jarvis.policy import Mode
from jarvis.stt import Transcript


def os_label() -> str:
    """Return the OS label as system-release."""
    return f"{platform.system().lower()}-{platform.release()}"


def display_server(environ: Mapping[str, str]) -> str | None:
    """Return the display server type if it is x11 or wayland."""
    session_type = environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type in ("x11", "wayland"):
        return session_type
    return None


def locale_tag(environ: Mapping[str, str]) -> str:
    """Return the locale tag from LC_ALL, LC_MESSAGES or LANG."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(var, "")
        if value:
            tag = value.split(".", 1)[0].split("@", 1)[0].replace("_", "-")
            if tag not in ("", "C", "POSIX"):
                return tag
    return "en-US"


def first_name(gecos: str) -> str:
    """Return the first name from a gecos field."""
    if not gecos:
        return ""
    part = gecos.split(",", 1)[0].strip()
    if not part:
        return ""
    return part.split()[0]


def user_info(address_as: str | None, gecos: str, login: str) -> UserInfo:
    """Build the UserInfo from address_as, gecos and login."""
    name = first_name(gecos) or login or "user"
    return UserInfo(name=name, address_as=address_as or first_name(gecos))


def _os_user() -> tuple[str, str]:
    """Return the gecos and login name of the current user."""
    try:
        import pwd  # noqa: PLC0415
    except ImportError:
        return ("", "")
    try:
        pw = pwd.getpwuid(os.getuid())
    except KeyError:
        return ("", "")
    return (pw.pw_gecos, pw.pw_name)


def build_envelope(  # noqa: PLR0913 - keyword-only; now/environ/turn_id are test seams
    *,
    command: str,
    raw_transcript: str,
    transcript: Transcript,
    settings: Settings,
    mode: Mode,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
    turn_id: str | None = None,
) -> TurnEnvelope:
    """Build the TurnEnvelope the brain receives."""
    now = now or datetime.now(UTC)
    environ = os.environ if environ is None else environ
    gecos, login = _os_user()
    if turn_id is None:
        turn_id = (
            now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{now.microsecond // 1000:03d}Z-"
            + secrets.token_hex(2)
        )
    return TurnEnvelope(
        turn_id=turn_id,
        command=command,
        raw_transcript=raw_transcript,
        # whisper-server reports no confidence, so it is always 1.0
        stt=SttInfo(engine=transcript.engine, confidence=1.0, language="en"),
        input_mode="voice",
        context=TurnContext(
            os=os_label(),
            display_server=display_server(environ),
            locale=locale_tag(environ),
            local_time=now.astimezone().isoformat(timespec="seconds"),
            user=user_info(settings.brain.address_as, gecos, login),
        ),
        policy=TurnPolicy(mode=mode, max_steps=settings.brain.max_steps),
    )
