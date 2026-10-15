"""The allowlisted environment of the brain's claude child (R45)."""

import sys
from collections.abc import Mapping

__all__ = ["brain_env"]

_ALLOWED = frozenset(
    {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TZ",
        "TMPDIR",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "NODE_EXTRA_CA_CERTS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
)

# Windows processes (python, node) cannot start without these; none of them holds a secret.
_WINDOWS_ALLOWED = frozenset(
    {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "USERNAME",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "TEMP",
        "TMP",
    }
)

_ALLOWED_PREFIXES = ("LC_", "XDG_")

_DENIED_PREFIXES = ("ANTHROPIC_", "CLAUDE", "MCP_", "OTEL_")


def brain_env(environ: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the explicit environment for the headless claude child."""
    result: dict[str, str] = {}
    for name, value in environ.items():
        if name.startswith(_DENIED_PREFIXES):
            continue
        if (
            name in _ALLOWED
            or name.startswith(_ALLOWED_PREFIXES)
            # Windows names are case-insensitive (os.environ upper-cases them), hence upper()
            or (sys.platform == "win32" and name.upper() in _WINDOWS_ALLOWED)
        ):
            result[name] = value
    if extra is not None:
        result.update(extra)
    return result
